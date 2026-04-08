use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScoredPostsQuery {
    pub viewer_id: i64,
    pub client_app_id: Option<i64>,
    pub country_code: Option<String>,
    pub language_code: Option<String>,
    pub seen_ids: Vec<i64>,
    pub served_ids: Vec<i64>,
    pub in_network_only: bool,
    pub request_id: String,
    pub user_action_sequence: Option<UserActionSequence>,
    pub bloom_filter_entries: Vec<BloomFilterEntry>,
    pub candidate_count: Option<usize>,

    // NEW — populated by Rust from Redis/Qdrant before pipeline runs:
    pub user_text_vector: Option<Vec<f64>>,   // 384-dim
    pub user_visual_vector: Option<Vec<f64>>, // 512-dim
    pub is_cold_start: bool,
    pub following_ids: Vec<i64>,
    pub blocked_ids: Vec<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UserActionSequence {
    // Placeholder for user action sequence
    pub actions: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BloomFilterEntry {
    pub bitset: Vec<u8>,
    pub num_hashes: u32,
    pub num_bits: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PostCandidate {
    pub tweet_id: i64,
    pub author_id: i64,
    pub created_at_ms: u64,
    pub in_network: Option<bool>,

    // Scores
    pub score: Option<f64>,
    pub weighted_score: Option<f64>,
    pub phoenix_scores: PhoenixScores,

    // Lineage / Relations
    pub retweeted_tweet_id: Option<i64>,
    pub retweeted_user_id: Option<i64>,
    pub in_reply_to_tweet_id: Option<i64>,
    pub ancestors: Vec<i64>,

    // Serving Info
    pub served_type: Option<ServedType>,
    pub visibility_reason: Option<VisibilityReason>,
    pub last_scored_at_ms: Option<u64>,
    pub prediction_request_id: Option<u64>,

    // Hydration
    pub is_hydrated: bool,
    pub author_is_blocked: bool,
    pub author_is_muted: bool,
    pub has_muted_keywords: bool,
    pub video_duration_ms: Option<i64>,

    // Neural Context
    pub semantic_alignment_score: Option<f64>,
    pub video_context: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PhoenixScores {
    pub favorite_score: Option<f64>,
    pub reply_score: Option<f64>,
    pub retweet_score: Option<f64>,
    pub photo_expand_score: Option<f64>,
    pub click_score: Option<f64>,
    pub profile_click_score: Option<f64>,
    pub vqv_score: Option<f64>,
    pub share_score: Option<f64>,
    pub share_via_dm_score: Option<f64>,
    pub share_via_copy_link_score: Option<f64>,
    pub dwell_score: Option<f64>,
    pub quote_score: Option<f64>,
    pub quoted_click_score: Option<f64>,
    pub dwell_time: Option<f64>,
    pub follow_author_score: Option<f64>,
    pub not_interested_score: Option<f64>,
    pub block_author_score: Option<f64>,
    pub mute_author_score: Option<f64>,
    pub report_score: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ServedType {
    ForYouPhoenixRetrieval,
    InNetwork,
    // Add others as needed
}

impl Default for ServedType {
    fn default() -> Self {
        ServedType::ForYouPhoenixRetrieval
    }
}

// Mimic protobuf enum
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum VisibilityReason {
    Safe,
    Unsafe,
}

impl From<VisibilityReason> for i32 {
    fn from(val: VisibilityReason) -> Self {
        match val {
            VisibilityReason::Safe => 0,
            VisibilityReason::Unsafe => 1,
        }
    }
}

// API Models
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedRequest {
    pub user_id: i64,
    pub limit: Option<usize>,
    pub cursor: Option<String>,
    pub candidate_count: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedResponse {
    pub request_id: String,
    pub feed: Vec<PostCandidate>,
    pub latency_ms: u128,
    pub feed_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestEvent {
    pub event_type: String,
    pub user_id: i64,
    pub payload: serde_json::Value,
}
