use crate::pipeline::Selector;
use crate::models::{PostCandidate, ScoredPostsQuery};
use crate::params;

pub struct TopKScoreSelector;

impl Selector for TopKScoreSelector {
    fn select(&self, _query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>) -> Vec<PostCandidate> {
        let k = params::RESULT_SIZE.min(candidates.len());
        if k == 0 { return Vec::new(); }

        // O(N) selection of top K elements
        candidates.select_nth_unstable_by(k - 1, |a, b| {
            b.score.unwrap_or(f64::MIN).partial_cmp(&a.score.unwrap_or(f64::MIN)).unwrap_or(std::cmp::Ordering::Equal)
        });
        
        candidates.truncate(k);
        candidates
    }
}
