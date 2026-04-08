use crate::models::{PostCandidate, ScoredPostsQuery};
use crate::pipeline::{Filter, FilterResult};
use async_trait::async_trait;
use std::time::Duration;

pub struct AgeFilter {
    pub max_age: Duration,
}

impl AgeFilter {
    pub fn new(max_age: Duration) -> Self {
        Self { max_age }
    }

    fn is_within_age(&self, candidate: &PostCandidate) -> bool {
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;

        if candidate.created_at_ms == 0 {
            return true; // No timestamp -> don't filter
        }

        let age = Duration::from_millis(now_ms.saturating_sub(candidate.created_at_ms));
        age <= self.max_age
    }
}

#[async_trait]
impl Filter for AgeFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let (kept, removed): (Vec<_>, Vec<_>) =
            candidates.into_iter().partition(|c| self.is_within_age(c));

        Ok(FilterResult { kept, removed })
    }
}
