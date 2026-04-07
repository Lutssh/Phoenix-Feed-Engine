mod api;
mod models;
mod state;
mod pipeline;
mod phoenix_pipeline;
mod sources;
mod hydrators;
mod filters;
mod scorers;
mod selectors;
mod util;
mod params;
mod extra_components;
mod interaction_handler;
mod interaction_weights;
mod user_store;
mod social_graph;

use axum::{
    routing::{get, post},
    Router,
};
use std::net::SocketAddr;
use std::sync::Arc;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
use crate::state::AppState;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "rust_feed_engine=info".into()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Load configuration
    dotenvy::dotenv().ok();
    let redis_url = std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());
    let qdrant_url = std::env::var("QDRANT_URL").unwrap_or_else(|_| "http://localhost:6334".to_string());
    
    // Initialize State
    let app_state = AppState::new(&redis_url, &qdrant_url).await.unwrap_or_else(|_| {
        panic!("Could not connect to Redis at {} or Qdrant at {}", redis_url, qdrant_url);
    });
    let shared_state = Arc::new(app_state);

    // BACKGROUND TASK: Keep Discovery Cache fresh
    let cache_state = shared_state.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(1));
        loop {
            interval.tick().await;
            let mut conn = cache_state.redis.clone();
            if let Ok(json_list) = redis::cmd("LRANGE").arg(crate::params::GLOBAL_DISCOVERY_KEY).arg(0).arg(99).query_async::<_, Vec<String>>(&mut conn).await {
                let mut new_posts = Vec::new();
                for json_str in json_list {
                    if let Ok(post) = serde_json::from_str::<crate::models::PostCandidate>(&json_str) {
                        new_posts.push(post);
                    }
                }
                let mut cache = cache_state.discovery_cache.write().await;
                *cache = new_posts;
            }
        }
    });

    // Build Router
    let app = Router::new()
        .route("/health", get(api::health_check))
        .route("/feed", post(api::get_feed))
        .route("/ingest", post(api::ingest_event))
        .route("/interaction", post(interaction_handler::handle_interaction))
        .with_state(shared_state);

    // Run Server
    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    tracing::info!("Feed Engine listening on {}", addr);
    
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
