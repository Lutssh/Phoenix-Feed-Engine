use crate::pipeline::Hydrator;
use crate::models::{PostCandidate, ScoredPostsQuery};
use async_trait::async_trait;

pub struct InNetworkCandidateHydrator;

#[async_trait]
impl Hydrator for InNetworkCandidateHydrator {
    async fn hydrate(&self, query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        let blocked_set: std::collections::HashSet<i64> = query.blocked_ids.iter().cloned().collect();
        let following_set: std::collections::HashSet<i64> = query.following_ids.iter().cloned().collect();
        
        for c in &mut candidates {
            c.author_is_blocked = blocked_set.contains(&c.author_id);
            c.in_network = Some(following_set.contains(&c.author_id));
            c.is_hydrated = true;
        }
        Ok(candidates)
    }
}

pub struct CoreDataCandidateHydrator;
#[async_trait]
impl Hydrator for CoreDataCandidateHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        Ok(candidates) // No-op for now
    }
}

pub struct VideoDurationCandidateHydrator;
#[async_trait]
impl Hydrator for VideoDurationCandidateHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
         for c in &mut candidates {
             // 10% chance of being a video
             if rand::random::<f64>() < 0.1 {
                 c.video_duration_ms = Some(10000);
             }
         }
        Ok(candidates)
    }
}

pub struct SubscriptionHydrator;
#[async_trait]
impl Hydrator for SubscriptionHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        Ok(candidates)
    }
}

pub struct GizmoduckCandidateHydrator;
#[async_trait]
impl Hydrator for GizmoduckCandidateHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        Ok(candidates)
    }
}

pub struct VFCandidateHydrator;
#[async_trait]
impl Hydrator for VFCandidateHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        Ok(candidates)
    }
}

pub struct NeuralContextHydrator {
    pub redis: redis::aio::ConnectionManager,
}

#[async_trait]
impl Hydrator for NeuralContextHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String> {
        use redis::AsyncCommands;
        let mut conn = self.redis.clone();
        
        for c in &mut candidates {
            let cache_key = format!("neural_context:{}", c.tweet_id);
            if let Ok(data) = conn.get::<_, String>(cache_key).await {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&data) {
                    c.semantic_alignment_score = json["semantic_alignment_score"].as_f64();
                    c.video_context = json["llava_description"].as_str().map(|s| s.to_string());
                }
            }
        }
        Ok(candidates)
    }
}
