// Scoring weights reflect the relative value of each engagement signal.
// Reply (27.0) ranks highest because it requires the most effort and
// most strongly indicates content resonance. Values are derived from
// public analysis of Twitter's open-sourced ranking model.
// These should be tuned via A/B testing once real engagement data exists.
pub const FAVORITE_WEIGHT: f64 = 0.5;
pub const REPLY_WEIGHT: f64 = 27.0;
pub const RETWEET_WEIGHT: f64 = 1.0;
pub const PHOTO_EXPAND_WEIGHT: f64 = 1.0; // Click
pub const CLICK_WEIGHT: f64 = 12.0; // Conversation click / Reply click
pub const PROFILE_CLICK_WEIGHT: f64 = 1.0;
pub const VQV_WEIGHT: f64 = 10.0; // Video Quality View
pub const SHARE_WEIGHT: f64 = 1.0;
pub const SHARE_VIA_DM_WEIGHT: f64 = 1.0;
pub const SHARE_VIA_COPY_LINK_WEIGHT: f64 = 1.0;
pub const DWELL_WEIGHT: f64 = 0.1;
pub const QUOTE_WEIGHT: f64 = 1.0;
pub const QUOTED_CLICK_WEIGHT: f64 = 1.0;
pub const CONT_DWELL_TIME_WEIGHT: f64 = 0.01;
pub const FOLLOW_AUTHOR_WEIGHT: f64 = 4.0;

// Negative weights (Penalties)
pub const NOT_INTERESTED_WEIGHT: f64 = -10.0;
pub const BLOCK_AUTHOR_WEIGHT: f64 = -100.0;
pub const MUTE_AUTHOR_WEIGHT: f64 = -100.0;
pub const REPORT_WEIGHT: f64 = -1000.0;

// Constants for Video Logic
pub const MIN_VIDEO_DURATION_MS: i64 = 5000;

// Normalization / Offset
pub const WEIGHTS_SUM: f64 = FAVORITE_WEIGHT
    + REPLY_WEIGHT
    + RETWEET_WEIGHT
    + PHOTO_EXPAND_WEIGHT
    + CLICK_WEIGHT
    + PROFILE_CLICK_WEIGHT
    + VQV_WEIGHT
    + SHARE_WEIGHT
    + SHARE_VIA_DM_WEIGHT
    + SHARE_VIA_COPY_LINK_WEIGHT
    + DWELL_WEIGHT
    + QUOTE_WEIGHT
    + QUOTED_CLICK_WEIGHT
    + CONT_DWELL_TIME_WEIGHT
    + FOLLOW_AUTHOR_WEIGHT; // Simplified sum of positives

pub const NEGATIVE_WEIGHTS_SUM: f64 =
    NOT_INTERESTED_WEIGHT + BLOCK_AUTHOR_WEIGHT + MUTE_AUTHOR_WEIGHT + REPORT_WEIGHT;

pub const NEGATIVE_SCORES_OFFSET: f64 = 0.0; // Keep it simple

pub const MAX_POST_AGE: u64 = 24 * 60 * 60; // 24 hours
pub const RESULT_SIZE: usize = 20;
pub const PHOENIX_MAX_RESULTS: i32 = 100;
pub const USER_ONLINE_TIMEOUT_SECS: u64 = 300; // 5 minutes
pub const GLOBAL_DISCOVERY_KEY: &str = "feed:global_discovery";
pub const HEARTBEAT_INTERVAL_SECS: u64 = 60;
