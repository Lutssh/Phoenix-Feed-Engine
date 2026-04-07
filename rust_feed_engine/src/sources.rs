use crate::pipeline::Source;
use crate::models::{PostCandidate, ScoredPostsQuery};
use async_trait::async_trait;
use qdrant_client::Qdrant;
use qdrant_client::qdrant::{SearchPointsBuilder, ScrollPointsBuilder, point_id::PointIdOptions};
use std::sync::Arc;
use std::collections::HashMap;

pub struct PhoenixSource {
    pub qdrant: Arc<Qdrant>,
}

#[async_trait]
impl Source for PhoenixSource {
    async fn get_candidates(&self, query: &ScoredPostsQuery) -> Result<Vec<PostCandidate>, String> {
        let mut all_candidates = HashMap::new();

        // 1. If cold start, run broad discovery (Bug 5: Use scroll for fresh content)
        if query.is_cold_start {
            let results = self.qdrant.scroll(
                ScrollPointsBuilder::new("text_meta_context")
                    .limit(100)
                    .with_payload(true)
            ).await.map_err(|e| e.to_string())?;

            for point in results.result {
                // Bug 1: Fallback to payload post_id
                let id = point.payload.get("post_id")
                    .and_then(|v| v.kind.as_ref())
                    .and_then(|k| match k {
                        qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse::<i64>().ok(),
                        qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                        _ => None,
                    }).unwrap_or_else(|| {
                        match point.id {
                            Some(ref id) => match id.point_id_options {
                                Some(PointIdOptions::Num(n)) => n as i64,
                                _ => 0,
                            },
                            None => 0,
                        }
                    });

                if id == 0 { continue; }

                let author_id = point.payload.get("author_id")
                    .and_then(|v| v.kind.as_ref())
                    .and_then(|k| match k {
                        qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse().ok(),
                        qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                        _ => None,
                    }).unwrap_or(0);

                all_candidates.insert(id, PostCandidate {
                    tweet_id: id,
                    author_id,
                    created_at_ms: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() * 1000,
                    in_network: Some(false),
                    is_hydrated: false,
                    ..Default::default()
                });
            }
        } else {
            // 2. Personalized Retrieval
            
            // Text Search (3,000 candidates)
            if let Some(text_vec) = &query.user_text_vector {
                let text_f32: Vec<f32> = text_vec.iter().map(|&x| x as f32).collect();
                let results = self.qdrant.search_points(
                    SearchPointsBuilder::new("text_meta_context", text_f32, 3000)
                        .with_payload(true)
                ).await.map_err(|e| e.to_string())?;

                for point in results.result {
                    // Bug 1: Fallback to payload post_id
                    let id = point.payload.get("post_id")
                        .and_then(|v| v.kind.as_ref())
                        .and_then(|k| match k {
                            qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse::<i64>().ok(),
                            qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                            _ => None,
                        }).unwrap_or_else(|| {
                            match point.id {
                                Some(ref id) => match id.point_id_options {
                                    Some(PointIdOptions::Num(n)) => n as i64,
                                    _ => 0,
                                },
                                None => 0,
                            }
                        });

                    if id == 0 { continue; }

                    let author_id = point.payload.get("author_id")
                        .and_then(|v| v.kind.as_ref())
                        .and_then(|k| match k {
                            qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse().ok(),
                            qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                            _ => None,
                        }).unwrap_or(0);

                    all_candidates.entry(id).or_insert(PostCandidate {
                        tweet_id: id,
                        author_id,
                        created_at_ms: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() * 1000,
                        in_network: Some(false),
                        is_hydrated: false,
                        ..Default::default()
                    });
                }
            }

            // Image/Video Search (2,000 candidates each)
            if let Some(visual_vec) = &query.user_visual_vector {
                let visual_f32: Vec<f32> = visual_vec.iter().map(|&x| x as f32).collect();

                for collection in &["image_meta_context", "video_meta_context"] {
                    let results = self.qdrant.search_points(
                        SearchPointsBuilder::new(*collection, visual_f32.clone(), 2000)
                            .with_payload(true)
                    ).await.map_err(|e| e.to_string())?;

                    for point in results.result {
                        // Bug 1: Fallback to payload post_id
                        let id = point.payload.get("post_id")
                            .and_then(|v| v.kind.as_ref())
                            .and_then(|k| match k {
                                qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse::<i64>().ok(),
                                qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                                _ => None,
                            }).unwrap_or_else(|| {
                                match point.id {
                                    Some(ref id) => match id.point_id_options {
                                        Some(PointIdOptions::Num(n)) => n as i64,
                                        _ => 0,
                                    },
                                    None => 0,
                                }
                            });

                        if id == 0 { continue; }

                        let author_id = point.payload.get("author_id")
                            .and_then(|v| v.kind.as_ref())
                            .and_then(|k| match k {
                                qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse().ok(),
                                qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                                _ => None,
                            }).unwrap_or(0);

                        all_candidates.entry(id).or_insert(PostCandidate {
                            tweet_id: id,
                            author_id,
                            created_at_ms: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() * 1000,
                            in_network: Some(false),
                            is_hydrated: false,
                            ..Default::default()
                        });
                    }
                }
            }
        }

        Ok(all_candidates.into_values().collect())
    }
}

pub struct ThunderSource {
    pub redis: redis::aio::ConnectionManager,
}

#[async_trait]
impl Source for ThunderSource {
    async fn get_candidates(&self, query: &ScoredPostsQuery) -> Result<Vec<PostCandidate>, String> {
        let mut conn = self.redis.clone();
        let mut candidates = Vec::new();

        use redis::AsyncCommands;
        for author_id in &query.following_ids {
            let author_feed_key = format!("author_posts:{}", author_id);
            if let Ok(recent_posts) = conn.lrange::<_, Vec<String>>(&author_feed_key, 0, 49).await {
                for json_str in recent_posts {
                    if let Ok(candidate) = serde_json::from_str::<PostCandidate>(&json_str) {
                        candidates.push(candidate);
                    }
                }
            }
            if candidates.len() >= 3000 { break; }
        }

        Ok(candidates)
    }
}
