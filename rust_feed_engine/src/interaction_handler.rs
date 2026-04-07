// rust_feed_engine/src/interaction_handler.rs
use axum::{extract::State, Json, http::StatusCode, response::IntoResponse};
use serde::{Deserialize, Serialize};
use crate::state::AppState;
use crate::interaction_weights::{get_weight, EMA_ALPHA};
use crate::user_store;
use redis::AsyncCommands;
use std::time::{SystemTime, UNIX_EPOCH};

use std::sync::Arc;

#[derive(Debug, Deserialize)]
pub struct InteractionRequest {
    pub user_id: i64,
    pub post_id: i64,
    pub action: String,
    pub post_type: String, // "text", "image", "video"
    pub author_id: i64,
    pub dwell_ms: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct NeuralContext {
    embedding: Vec<f64>,
    // Other fields exist but we only need embedding for EMA
}

pub async fn handle_interaction(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<InteractionRequest>,
) -> impl IntoResponse {
    let weight = get_weight(&payload.action);
    if weight == 0.0 && payload.action != "dwell" && payload.action != "skip" {
        return (StatusCode::BAD_REQUEST, Json(serde_json::json!({"error": "unknown action"}))).into_response();
    }

    let mut redis_conn = state.redis.clone();

    // 1. Write raw event to Redis Stream
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis();
    let _: Result<(), _> = redis_conn.xadd(
        "interactions:stream",
        "*",
        &[
            ("user_id", payload.user_id.to_string()),
            ("post_id", payload.post_id.to_string()),
            ("action", payload.action.clone()),
            ("post_type", payload.post_type.clone()),
            ("author_id", payload.author_id.to_string()),
            ("dwell_ms", payload.dwell_ms.unwrap_or(0).to_string()),
            ("timestamp", timestamp.to_string()),
        ],
    ).await;

    // 2. Fetch post vector from Redis
    let neural_key = format!("neural_context:{}", payload.post_id);
    let neural_data: Option<String> = redis_conn.get(&neural_key).await.unwrap_or(None);
    
    let post_vec = if let Some(data) = neural_data {
        if let Ok(ctx) = serde_json::from_str::<NeuralContext>(&data) {
            ctx.embedding
        } else {
            return (StatusCode::ACCEPTED, Json(serde_json::json!({"status": "malformed neural context"}))).into_response();
        }
    } else {
        // Post might still be ingesting
        return (StatusCode::ACCEPTED, Json(serde_json::json!({"status": "pending ingestion"}))).into_response();
    };

    // 3. Fetch current user vectors
    let (mut text_vec, mut visual_vec) = match user_store::get_user_vectors(payload.user_id, &mut redis_conn, &state.qdrant).await {
        Ok(v) => v,
        Err(_) => (vec![0.0; 384], vec![0.0; 512]),
    };

    // 4. Apply EMA update
    if payload.post_type == "text" {
        if post_vec.len() == 384 {
            text_vec = user_store::ema_update(&text_vec, &post_vec, weight, EMA_ALPHA);
        }
    } else if payload.post_type == "image" || payload.post_type == "video" {
        if post_vec.len() == 512 {
            visual_vec = user_store::ema_update(&visual_vec, &post_vec, weight, EMA_ALPHA);
        }
    }

    // 5. Write updated vectors back
    let _ = user_store::set_user_vectors(payload.user_id, text_vec, visual_vec, &mut redis_conn, &state.qdrant).await;

    // 6. Append to action sequence
    let _ = user_store::append_action(payload.user_id, &payload.action, payload.post_id, &mut redis_conn).await;

    // 7. Mark user online
    let _: Result<(), _> = redis_conn.zadd("online_users", payload.user_id, timestamp as u64).await;

    // 8. Increment interaction count
    let _ = user_store::increment_interaction_count(payload.user_id, &mut redis_conn).await;

    (StatusCode::OK, Json(serde_json::json!({"status": "processed"}))).into_response()
}
