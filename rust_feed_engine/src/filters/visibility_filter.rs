use crate::pipeline::{Filter, FilterResult};
use crate::models::{PostCandidate, ScoredPostsQuery, VisibilityReason};
use async_trait::async_trait;

pub struct VisibilityFilter;

#[async_trait]
impl Filter for VisibilityFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let (kept, removed): (Vec<_>, Vec<_>) = candidates
            .into_iter()
            .partition(|c| {
                match &c.visibility_reason {
                    Some(VisibilityReason::Unsafe) => false,
                    _ => true,
                }
            });

        Ok(FilterResult { kept, removed })
    }
}
