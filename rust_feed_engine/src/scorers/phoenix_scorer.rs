use crate::pipeline::Scorer;
use crate::models::{PostCandidate, ScoredPostsQuery, PhoenixScores};
use async_trait::async_trait;
use rand::Rng;

pub struct PhoenixScorer;

#[async_trait]
impl Scorer for PhoenixScorer {
    async fn score(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<Vec<PostCandidate>, String> {
        let scored = candidates
            .into_iter()
            .map(|mut c| {
                let mut rng = rand::thread_rng();
                c.phoenix_scores = PhoenixScores {
                    favorite_score: Some(rng.gen_range(0.0..0.1)),
                    reply_score: Some(rng.gen_range(0.0..0.05)),
                    retweet_score: Some(rng.gen_range(0.0..0.02)),
                    click_score: Some(rng.gen_range(0.0..0.2)),
                    dwell_time: Some(rng.gen_range(0.0..120.0)),
                    ..Default::default()
                };
                c.last_scored_at_ms = Some(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as u64);
                c
            })
            .collect();
            
        Ok(scored)
    }
}