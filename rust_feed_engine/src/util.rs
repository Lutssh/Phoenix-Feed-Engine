use std::time::Duration;

pub mod snowflake {
    use super::*;
    
    // Twitter Snowflake format:
    // Bits 0-40: Timestamp (ms) since Twitter Epoch (2010-11-04 01:42:54.657 UTC)
    // Bits 41-50: Machine ID
    // Bits 51-62: Sequence number
    
    pub const TWITTER_EPOCH: u64 = 1288834974657;

    pub fn duration_since_creation_opt(tweet_id: i64) -> Option<Duration> {
        if tweet_id <= 0 {
            return None;
        }
        let id = tweet_id as u64;
        let timestamp_ms = (id >> 22) + TWITTER_EPOCH;
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_millis() as u64;
            
        if now_ms >= timestamp_ms {
            Some(Duration::from_millis(now_ms - timestamp_ms))
        } else {
            None // Tweet is from the future?
        }
    }
}

pub mod bloom_filter {
    use crate::models::BloomFilterEntry;
    
    pub struct BloomFilter {
        // Simple stub for now
    }
    
    impl BloomFilter {
        pub fn from_entry(_entry: &BloomFilterEntry) -> Self {
            BloomFilter {}
        }
        
        pub fn may_contain(&self, _id: i64) -> bool {
            false // Stub: always return false so we don't filter out things incorrectly without real data
        }
    }
}

pub mod candidates_util {
    use crate::models::PostCandidate;
    
    pub fn get_related_post_ids(candidate: &PostCandidate) -> Vec<i64> {
        let mut ids = vec![candidate.tweet_id];
        if let Some(rt_id) = candidate.retweeted_tweet_id {
            ids.push(rt_id);
        }
        if let Some(reply_id) = candidate.in_reply_to_tweet_id {
            ids.push(reply_id);
        }
        ids
    }
}

pub mod score_normalizer {
    use crate::models::PostCandidate;
    
    pub fn normalize_score(_candidate: &PostCandidate, score: f64) -> f64 {
        // Placeholder for actual normalization logic if it exists.
        // For now, identity.
        score
    }
}
