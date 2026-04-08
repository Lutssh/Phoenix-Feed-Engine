// rust_feed_engine/src/interaction_weights.rs
pub fn get_weight(action: &str) -> f64 {
    match action {
        "like" => 1.0,
        "share" => 1.5, // strongest positive signal
        "reply" => 1.2,
        "dwell" => 0.8, // implicit but reliable
        "click" => 0.5,
        "follow" => 1.3,
        "skip" => -0.3, // mild negative
        "hide" => -0.8,
        "not_interested" => -1.5,
        "report" => -2.0, // strongest negative signal
        _ => 0.0,
    }
}

pub const EMA_ALPHA: f64 = 0.3;
// 0.3 means recent interactions count for 30% of the update.
// History is preserved at 70%. Balances responsiveness vs stability.

pub const COLD_START_THRESHOLD: u64 = 5;
// Fewer than 5 interactions = cold start user.
// Cold start users get discovery-heavy feeds, not personalised ones.
