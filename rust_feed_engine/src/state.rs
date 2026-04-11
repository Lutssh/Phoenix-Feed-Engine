use crate::models::PostCandidate;
use crate::phoenix_pipeline::PhoenixCandidatePipeline;
use anyhow::Result;
use dashmap::DashMap;
use qdrant_client::Qdrant;
use redis::aio::ConnectionManager;
use redis::Client;
use reqwest::Client as HttpClient;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone)]
pub struct AppState {
    pub redis: ConnectionManager,
    pub qdrant: Arc<Qdrant>,
    pub http_client: HttpClient,
    pub pipeline: Arc<PhoenixCandidatePipeline>,
    pub heartbeat_cache: Arc<DashMap<i64, u64>>,
    pub discovery_cache: Arc<RwLock<Vec<PostCandidate>>>,
}

impl AppState {
    pub async fn new(redis_url: &str, qdrant_url: &str) -> Result<Self> {
        let client = Client::open(redis_url)?;
        let connection_manager = client.get_connection_manager().await?;

        let qdrant = Arc::new(Qdrant::from_url(qdrant_url).build()?);
        let http_client = HttpClient::new();
        let pipeline = Arc::new(PhoenixCandidatePipeline::new(
            connection_manager.clone(),
            qdrant.clone(),
        ));
        let heartbeat_cache = Arc::new(DashMap::new());
        let discovery_cache = Arc::new(RwLock::new(Vec::new()));

        Ok(Self {
            redis: connection_manager,
            qdrant,
            http_client,
            pipeline,
            heartbeat_cache,
            discovery_cache,
        })
    }
}
