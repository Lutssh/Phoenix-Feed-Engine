use crate::models::{PostCandidate, ScoredPostsQuery, UserActionSequence};
use crate::pipeline::{QueryHydrator, SideEffect};
use async_trait::async_trait;

pub struct UserActionSeqQueryHydrator;
#[async_trait]
impl QueryHydrator for UserActionSeqQueryHydrator {
    async fn hydrate(&self, _query: &mut ScoredPostsQuery) -> Result<(), String> {
        Ok(())
    }
}

use redis::aio::ConnectionManager;
use redis::AsyncCommands;

pub struct CacheRequestInfoSideEffect {
    pub redis: ConnectionManager,
}

#[async_trait]
impl SideEffect for CacheRequestInfoSideEffect {
    async fn execute(&self, query: &ScoredPostsQuery, candidates: &[PostCandidate]) {
        let mut redis_conn = self.redis.clone();
        let user_id = query.viewer_id;
        let key = format!("served_posts:{}", user_id);

        let post_ids: Vec<i64> = candidates.iter().map(|c| c.tweet_id).collect();
        if !post_ids.is_empty() {
            let _: Result<(), _> = redis_conn.sadd(&key, post_ids).await;
            let _: Result<(), _> = redis_conn.expire(&key, 86400).await;
        }

        tracing::info!(
            "SideEffect: Cached {} served posts for user {}",
            candidates.len(),
            user_id
        );
    }
}
