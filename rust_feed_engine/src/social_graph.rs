// rust_feed_engine/src/social_graph.rs
use anyhow::Result;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SocialGraph {
    pub following: Vec<i64>,
    pub blocked: Vec<i64>,
}

pub async fn get_social_graph(
    user_id: i64,
    http_client: &reqwest::Client,
    redis: &mut redis::aio::ConnectionManager,
) -> Result<(Vec<i64>, Vec<i64>)> {
    let cache_key = format!("social_graph:{}", user_id);

    // 1. Try Redis Cache
    if let Ok(Some(cached)) = redis.get::<_, Option<String>>(&cache_key).await {
        if let Ok(graph) = serde_json::from_str::<SocialGraph>(&cached) {
            return Ok((graph.following, graph.blocked));
        }
    }

    // 2. Fallback to Backend Internal API
    let backend_url =
        std::env::var("BACKEND_URL").unwrap_or_else(|_| "http://localhost:8000".to_string());
    let url = format!("{}/internal/social-graph/{}/", backend_url, user_id);

    let response = http_client
        .get(&url)
        .header(
            "X-Internal-Key",
            std::env::var("INTERNAL_API_KEY").unwrap_or_default(),
        )
        .timeout(Duration::from_millis(200))
        .send()
        .await?;

    if response.status().is_success() {
        let graph: SocialGraph = response.json().await?;

        // Update Redis cache (60s TTL)
        let _: () = redis
            .set_ex(&cache_key, serde_json::to_string(&graph)?, 60)
            .await?;

        Ok((graph.following, graph.blocked))
    } else {
        // Return empty if Django fails
        Ok((vec![], vec![]))
    }
}
