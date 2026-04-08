use crate::filters::FilterResult;
use crate::models::{PostCandidate, ScoredPostsQuery};
use crate::pipeline::Filter;
use async_trait::async_trait;

pub struct RetweetDeduplicationFilter;

#[async_trait]
impl Filter for RetweetDeduplicationFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let mut seen_tweets = std::collections::HashSet::new();
        let (kept, removed): (Vec<_>, Vec<_>) = candidates.into_iter().partition(|c| {
            let id_to_check = c.retweeted_tweet_id.unwrap_or(c.tweet_id);
            if seen_tweets.contains(&id_to_check) {
                false
            } else {
                seen_tweets.insert(id_to_check);
                true
            }
        });

        Ok(FilterResult { kept, removed })
    }
}

pub struct AuthorSocialgraphFilter;
#[async_trait]
impl Filter for AuthorSocialgraphFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        // Mock: Filter out if author is blocked/muted (hydrated earlier)
        let (kept, removed): (Vec<_>, Vec<_>) = candidates
            .into_iter()
            .partition(|c| !c.author_is_blocked && !c.author_is_muted);
        Ok(FilterResult { kept, removed })
    }
}

pub struct MutedKeywordFilter;
#[async_trait]
impl Filter for MutedKeywordFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let (kept, removed): (Vec<_>, Vec<_>) =
            candidates.into_iter().partition(|c| !c.has_muted_keywords);
        Ok(FilterResult { kept, removed })
    }
}
