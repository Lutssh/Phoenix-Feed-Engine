use crate::models::{FeedRequest, FeedResponse, IngestEvent, PostCandidate, ScoredPostsQuery};
use crate::pipeline::CandidatePipeline;
use crate::state::AppState;
use crate::{social_graph, user_store};
use axum::{
    extract::{Json, State},
    http::StatusCode,
    response::IntoResponse,
};
use redis::AsyncCommands;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Semaphore;
use tracing::info;
use uuid::Uuid;

lazy_static::lazy_static! {
    static ref DEEP_DISCOVERY_SEMAPHORE: Arc<Semaphore> = Arc::new(Semaphore::new(50));
}

pub async fn health_check() -> impl IntoResponse {
    (StatusCode::OK, "Service is healthy")
}

pub async fn get_feed(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<FeedRequest>,
) -> impl IntoResponse {
    let start = Instant::now();
    let request_id = Uuid::new_v4().to_string();
    let user_id = payload.user_id;
    let redis_key = format!("feed:{}", user_id);
    let online_key = "online_users";
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();

    // Heartbeat Throttling: Only update Redis if heartbeat cache is stale
    let should_update_heartbeat = match state.heartbeat_cache.get(&user_id) {
        Some(last_ts) => now > *last_ts + crate::params::HEARTBEAT_INTERVAL_SECS,
        None => true,
    };

    if should_update_heartbeat {
        state.heartbeat_cache.insert(user_id, now);
        let mut redis_conn_bg = state.redis.clone();
        tokio::spawn(async move {
            let _: Result<(), _> = redis_conn_bg
                .zadd(
                    online_key,
                    user_id,
                    now + crate::params::USER_ONLINE_TIMEOUT_SECS,
                )
                .await;
        });
    }

    let mut redis_conn = state.redis.clone();

    // 1. Try to fetch from Precomputed "Personal Push" Queue (Personal Redis)
    let mut feed: Vec<PostCandidate> = Vec::new();
    let limit = payload.limit.unwrap_or(20);
    let mut feed_type = "none";

    if let Ok(cached_json) = redis_conn
        .lpop::<_, Vec<String>>(&redis_key, NonZeroUsize::new(limit))
        .await
    {
        for json_str in cached_json {
            if let Ok(mut post) = serde_json::from_str::<PostCandidate>(&json_str) {
                post.is_hydrated = true;
                feed.push(post);
            }
        }
    }

    if !feed.is_empty() {
        feed_type = "push";
    }

    // 2. If empty (Cold Start), run the "Lite" pipeline for instant Social Graph results
    if feed.is_empty() {
        let mut redis_conn = state.redis.clone();

        // Load user context (vectors, cold start, social graph)
        let (text_vec, visual_vec) =
            user_store::get_user_vectors(user_id, &mut redis_conn, &state.qdrant)
                .await
                .unwrap_or((vec![0.0; 384], vec![0.0; 512]));
        let is_cold = user_store::is_cold_start(user_id, &mut redis_conn)
            .await
            .unwrap_or(true);
        let (following, blocked) =
            social_graph::get_social_graph(user_id, &state.http_client, &mut redis_conn)
                .await
                .unwrap_or((vec![], vec![]));

        // Bug 4 & Missing 1: Load seen, served, and action sequence
        let seen_ids: Vec<i64> = redis_conn
            .smembers::<_, Vec<String>>(format!("seen_posts:{}", user_id))
            .await
            .unwrap_or_default()
            .iter()
            .filter_map(|s| s.parse().ok())
            .collect();

        let served_ids: Vec<i64> = redis_conn
            .smembers::<_, Vec<String>>(format!("served_posts:{}", user_id))
            .await
            .unwrap_or_default()
            .iter()
            .filter_map(|s| s.parse().ok())
            .collect();

        let action_sequence = user_store::get_action_sequence(user_id, 50, &mut redis_conn)
            .await
            .unwrap_or_default();

        let count = payload.candidate_count.unwrap_or(10);
        let query = ScoredPostsQuery {
            viewer_id: user_id,
            request_id: request_id.clone(),
            in_network_only: false, // Changed to false to allow out-of-network results via ANN
            candidate_count: Some(count),
            user_text_vector: Some(text_vec),
            user_visual_vector: Some(visual_vec),
            is_cold_start: is_cold,
            following_ids: following,
            blocked_ids: blocked,
            seen_ids,
            served_ids,
            user_action_sequence: Some(crate::models::UserActionSequence {
                actions: action_sequence,
            }),
            ..Default::default()
        };

        if let Ok(lite_posts) = state.pipeline.execute(query.clone()).await {
            if !lite_posts.is_empty() {
                feed.extend(lite_posts);
                feed_type = "lite";
            }
        }

        // Background ML training (fire and forget, no semaphore queuing)
        let state_clone = state.clone();
        tokio::spawn(async move {
            let _ = state_clone.pipeline.execute(query).await;
        });
    }

    // 4. Fallback to Global Discovery Cache (In-Memory) to fill remaining slots
    if feed.len() < limit {
        let cache = state.discovery_cache.read().await;
        if !cache.is_empty() {
            let needed = limit.saturating_sub(feed.len());
            let prev_len = feed.len();
            feed.extend(cache.iter().take(needed).cloned());

            if feed_type == "none" || (feed_type == "lite" && prev_len < (limit / 2)) {
                feed_type = "discovery";
            }
        }
    }

    // Bug 4: Write served IDs back
    if !feed.is_empty() {
        let served_key = format!("served_posts:{}", user_id);
        let ids: Vec<String> = feed.iter().map(|p| p.tweet_id.to_string()).collect();
        let mut redis_conn_bg = state.redis.clone();
        tokio::spawn(async move {
            let _: Result<(), _> = redis_conn_bg.sadd(&served_key, ids).await;
            let _: Result<(), _> = redis_conn_bg.expire(&served_key, 86400).await;
        });
    }

    let latency = start.elapsed().as_millis();
    (
        StatusCode::OK,
        Json(FeedResponse {
            request_id,
            feed,
            latency_ms: latency,
            feed_type: feed_type.to_string(),
        }),
    )
}

pub async fn ingest_event(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<IngestEvent>,
) -> impl IntoResponse {
    if payload.event_type == "new_post" {
        let state_clone = state.clone();
        tokio::spawn(async move {
            let start = Instant::now();
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs();
            let mut redis_conn = state_clone.redis.clone();

            let post_data = payload.payload;
            let candidate = PostCandidate {
                tweet_id: post_data["id"].as_i64().unwrap_or(0),
                author_id: post_data["author_id"].as_i64().unwrap_or(0),
                created_at_ms: now * 1000,
                is_hydrated: true,
                in_network: Some(false),
                ..Default::default()
            };

            if let Ok(serialized) = serde_json::to_string(&candidate) {
                // 1. Push to GLOBAL DISCOVERY
                let _: Result<(), _> = redis_conn
                    .lpush(crate::params::GLOBAL_DISCOVERY_KEY, &serialized)
                    .await;
                let _: Result<(), _> = redis_conn
                    .ltrim(crate::params::GLOBAL_DISCOVERY_KEY, 0, 4999)
                    .await;

                // 2. Push to AUTHOR'S POST LIST (Fix for Bug 2)
                let author_key = format!("author_posts:{}", candidate.author_id);
                let _: Result<(), _> = redis_conn.lpush(&author_key, &serialized).await;
                let _: Result<(), _> = redis_conn.ltrim(&author_key, 0, 199).await;

                // 3. CHUNKED FAN-OUT to Online Users (Prevents Redis blocking)
                let online_key = "online_users";
                if let Ok(uids) = redis_conn
                    .zrangebyscore::<_, _, _, Vec<i64>>(online_key, now, "+inf")
                    .await
                {
                    for chunk in uids.chunks(500) {
                        let mut pipe = redis::pipe();
                        for uid in chunk {
                            let user_feed_key = format!("feed:{}", uid);
                            pipe.lpush(&user_feed_key, &serialized)
                                .ltrim(&user_feed_key, 0, 99)
                                .ignore();
                        }
                        let _: Result<(), _> = pipe.query_async(&mut redis_conn).await;
                        tokio::task::yield_now().await; // Give other tasks a chance to use Redis
                    }
                }
                info!(
                    "Ingestion & Fan-out completed in {}ms",
                    start.elapsed().as_millis()
                );
            }
        });
        return (StatusCode::ACCEPTED, "Ingestion queued");
    }

    (StatusCode::ACCEPTED, "Event Processed")
}
