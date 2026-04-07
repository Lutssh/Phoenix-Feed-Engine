use crate::pipeline::Scorer;
use crate::models::{PostCandidate, ScoredPostsQuery};
use async_trait::async_trait;
use std::collections::HashMap;

pub struct AuthorDiversityScorer;

#[async_trait]
impl Scorer for AuthorDiversityScorer {
    async fn score(
        &self,
        _query: &ScoredPostsQuery,
        mut candidates: Vec<PostCandidate>,
    ) -> Result<Vec<PostCandidate>, String> {
        let mut author_counts = HashMap::new();
        
        // Penality for having too many posts from the same author
        for c in &mut candidates {
            let count = author_counts.entry(c.author_id).or_insert(0);
            *count += 1;
            
            if *count > 1 {
                // Apply a simple diversity penalty
                if let Some(score) = c.score {
                    c.score = Some(score * 0.8_f64.powi(*count - 1));
                }
            }
        }
        
        Ok(candidates)
    }
}
