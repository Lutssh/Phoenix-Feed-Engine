use crate::models::{PhoenixScores, PostCandidate, ScoredPostsQuery};
use crate::params as p;
use crate::pipeline::Scorer;
use crate::util::score_normalizer::normalize_score;
use async_trait::async_trait;

pub struct WeightedScorer;

#[async_trait]
impl Scorer for WeightedScorer {
    async fn score(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<Vec<PostCandidate>, String> {
        let scored = candidates
            .into_iter()
            .map(|mut c| {
                let weighted_score = Self::compute_weighted_score(&c);
                let normalized_weighted_score = normalize_score(&c, weighted_score);

                c.weighted_score = Some(normalized_weighted_score);
                c.score = Some(normalized_weighted_score); // Set primary score as well
                c
            })
            .collect();

        Ok(scored)
    }
}

impl WeightedScorer {
    fn apply(score: Option<f64>, weight: f64) -> f64 {
        score.unwrap_or(0.0) * weight
    }

    fn compute_weighted_score(candidate: &PostCandidate) -> f64 {
        let s: &PhoenixScores = &candidate.phoenix_scores;

        let vqv_weight = Self::vqv_weight_eligibility(candidate);

        // Base score from behavioral signals
        let mut combined_score = Self::apply(s.favorite_score, p::FAVORITE_WEIGHT)
            + Self::apply(s.reply_score, p::REPLY_WEIGHT)
            + Self::apply(s.retweet_score, p::RETWEET_WEIGHT)
            + Self::apply(s.photo_expand_score, p::PHOTO_EXPAND_WEIGHT)
            + Self::apply(s.click_score, p::CLICK_WEIGHT)
            + Self::apply(s.profile_click_score, p::PROFILE_CLICK_WEIGHT)
            + Self::apply(s.vqv_score, vqv_weight)
            + Self::apply(s.share_score, p::SHARE_WEIGHT)
            + Self::apply(s.share_via_dm_score, p::SHARE_VIA_DM_WEIGHT)
            + Self::apply(s.share_via_copy_link_score, p::SHARE_VIA_COPY_LINK_WEIGHT)
            + Self::apply(s.dwell_score, p::DWELL_WEIGHT)
            + Self::apply(s.quote_score, p::QUOTE_WEIGHT)
            + Self::apply(s.quoted_click_score, p::QUOTED_CLICK_WEIGHT)
            + Self::apply(s.dwell_time, p::CONT_DWELL_TIME_WEIGHT)
            + Self::apply(s.follow_author_score, p::FOLLOW_AUTHOR_WEIGHT)
            + Self::apply(s.not_interested_score, p::NOT_INTERESTED_WEIGHT)
            + Self::apply(s.block_author_score, p::BLOCK_AUTHOR_WEIGHT)
            + Self::apply(s.mute_author_score, p::MUTE_AUTHOR_WEIGHT)
            + Self::apply(s.report_score, p::REPORT_WEIGHT);

        // Neural Boost: Reward high-quality semantic alignment
        if let Some(alignment) = candidate.semantic_alignment_score {
            // We boost the score by a factor of the alignment (0.0 to 1.0)
            // This favors posts where the caption accurately describes the video
            combined_score *= 1.0 + (alignment * 0.2); // Up to 20% boost
        }

        Self::offset_score(combined_score)
    }

    fn vqv_weight_eligibility(candidate: &PostCandidate) -> f64 {
        if candidate
            .video_duration_ms
            .is_some_and(|ms| ms > p::MIN_VIDEO_DURATION_MS)
        {
            p::VQV_WEIGHT
        } else {
            0.0
        }
    }

    fn offset_score(combined_score: f64) -> f64 {
        if p::WEIGHTS_SUM == 0.0 {
            combined_score.max(0.0)
        } else if combined_score < 0.0 {
            (combined_score + p::NEGATIVE_WEIGHTS_SUM.abs()) * 0.1
        } else {
            combined_score + p::NEGATIVE_SCORES_OFFSET
        }
    }
}
