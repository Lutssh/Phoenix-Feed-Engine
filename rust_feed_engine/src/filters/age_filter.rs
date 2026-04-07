use crate::pipeline::{Filter, FilterResult};
use crate::models::{PostCandidate, ScoredPostsQuery};
use crate::util::snowflake;
use async_trait::async_trait;
use std::time::Duration;

pub struct AgeFilter {
    pub max_age: Duration,
}

impl AgeFilter {
    pub fn new(max_age: Duration) -> Self {
        Self { max_age }
    }

    fn is_within_age(&self, tweet_id: i64) -> bool {
        snowflake::duration_since_creation_opt(tweet_id)
            .map(|age| age <= self.max_age)
            .unwrap_or(false)
    }
}

#[async_trait]
impl Filter for AgeFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let (kept, removed): (Vec<_>, Vec<_>) = candidates
            .into_iter()
            .partition(|c| self.is_within_age(c.tweet_id));

        Ok(FilterResult { kept, removed })
    }
}