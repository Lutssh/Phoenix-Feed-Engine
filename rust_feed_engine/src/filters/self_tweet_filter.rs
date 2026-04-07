use crate::pipeline::{Filter, FilterResult};
use crate::models::{PostCandidate, ScoredPostsQuery};
use async_trait::async_trait;

pub struct SelfTweetFilter;

#[async_trait]
impl Filter for SelfTweetFilter {
    async fn filter(
        &self,
        query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let viewer_id = query.viewer_id;
        let (kept, removed): (Vec<_>, Vec<_>) = candidates
            .into_iter()
            .partition(|c| c.author_id != viewer_id);

        Ok(FilterResult { kept, removed })
    }
}