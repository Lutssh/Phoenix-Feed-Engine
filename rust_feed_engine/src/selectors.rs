use crate::models::{PostCandidate, ScoredPostsQuery};
use crate::params;
use crate::pipeline::Selector;

pub struct TopKScoreSelector;

impl Selector for TopKScoreSelector {
    fn select(
        &self,
        query: &ScoredPostsQuery,
        mut candidates: Vec<PostCandidate>,
    ) -> Vec<PostCandidate> {
        // Use requested limit if provided, fall back to RESULT_SIZE
        let k = query
            .candidate_count
            .unwrap_or(params::RESULT_SIZE)
            .min(params::RESULT_SIZE) // cap at max
            .min(candidates.len());

        if k == 0 {
            return Vec::new();
        }

        // O(N) selection of top K elements
        candidates.select_nth_unstable_by(k - 1, |a, b| {
            b.score
                .unwrap_or(f64::MIN)
                .partial_cmp(&a.score.unwrap_or(f64::MIN))
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        candidates.truncate(k);
        candidates
    }
}
