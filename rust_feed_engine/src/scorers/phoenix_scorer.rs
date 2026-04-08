use crate::models::{PhoenixScores, PostCandidate, ScoredPostsQuery};
use crate::pipeline::Scorer;
use async_trait::async_trait;

pub struct PhoenixScorer;

#[async_trait]
impl Scorer for PhoenixScorer {
    async fn score(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<Vec<PostCandidate>, String> {
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        let scored = candidates
            .into_iter()
            .map(|mut c| {
                // Freshness score: posts decay over 24h
                let age_ms = now_ms.saturating_sub(c.created_at_ms);
                let freshness = (1.0 - (age_ms as f64 / (24.0 * 3600.0 * 1000.0))).max(0.0);

                // In-network boost
                let network_boost = if c.in_network.unwrap_or(false) {
                    1.5
                } else {
                    1.0
                };

                // Alignment quality signal (from smart_ingestion)
                let alignment = c.semantic_alignment_score.unwrap_or(0.5).max(0.0);

                c.phoenix_scores = PhoenixScores {
                    // Map real signals to score fields WeightedScorer reads
                    favorite_score: Some(alignment * 0.3),
                    click_score: Some(freshness * 0.5),
                    dwell_time: Some(freshness * network_boost * 60.0),
                    follow_author_score: if c.in_network.unwrap_or(false) {
                        Some(1.0)
                    } else {
                        Some(0.0)
                    },
                    ..Default::default()
                };

                c.last_scored_at_ms = Some(now_ms);
                c
            })
            .collect();

        Ok(scored)
    }
}
