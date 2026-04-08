# Feed Algorithm — Full Codebase Audit
## Pipeline Trace, Bug Report, Security Review & Clean Code Guide

> Prepared after reading every file in the repository.
> Priority order: Critical bugs → Security → Clean code → Optimisations.

---

## Part 1 — Pipeline Trace (How It Actually Works)

Before fixing anything, understand exactly what the code does end-to-end.

### 1.1 Content Enters the System (Post Created)

```
Django (your app) calls signals_client.trigger_ingestion()
  → POST /ingest  to Rust engine
      Rust api.rs ingest_event handler runs:
        - Creates a PostCandidate struct with tweet_id and author_id
        - Pushes serialised candidate to Redis:
            LPUSH feed:global_discovery  {candidate JSON}
            LTRIM feed:global_discovery  0 4999
            LPUSH author_posts:{author_id}  {candidate JSON}   ← Bug 2 fix present
            LTRIM author_posts:{author_id}  0 199
        - Fan-out to online users:
            ZRANGEBYSCORE online_users {now} +inf → list of online user IDs
            For each chunk of 500: pipeline LPUSH feed:{user_id} + LTRIM
        - Returns 202 Accepted immediately

Separately — Django also calls smart_ingestion workers:
  Text post  → process_text.delay(text, post_id)
               Celery worker: MiniLM embeds text → 384-dim vector
               Writes to Qdrant: text_meta_context
               Writes to Redis:  neural_context:{post_id}

  Image post → process_image.delay(image_path, post_id, caption)
               Celery worker: CLIP embeds image → 512-dim vector
                              YOLOv8n detects objects → tag list
               Writes to Qdrant: image_meta_context
               Writes to Redis:  neural_context:{post_id}

  Video post → ingest_video(video_path, post_id, caption)
               Celery chord — 3 parallel tasks:
                 clip_frames_task   → 512-dim CLIP visual fingerprint
                 transcribe_task    → Whisper transcript string
                 detect_objects_task→ YOLO object tags
               chord callback: synthesize_and_index
                 Computes alignment_score (CLIP image vs CLIP text)
                 Writes to Qdrant: video_meta_context
                 Writes to Redis:  neural_context:{post_id}
```

### 1.2 User Interacts With a Post

```
Django view calls signals_client.record_interaction()
  → POST /interaction  to Rust engine
      Rust interaction_handler.rs handle_interaction runs:
        1. Validates action string (returns 400 on unknown)
        2. XADD interactions:stream  (raw event log)
        3. GET neural_context:{post_id}  from Redis
           Parses JSON → extracts "embedding" field as Vec<f64>
           If miss → returns 202 "pending ingestion"
        4. Gets current user vectors:
             GET user_vector:{user_id}  from Redis (hot cache)
             If miss → fetch from Qdrant user_profiles
             If Qdrant miss → return zero vectors (cold start)
        5. Applies EMA update (pure Rust arithmetic):
             text post  → updates text_vector  (384-dim)
             image/video→ updates visual_vector (512-dim)
             weight = interaction_weights::get_weight(action)
             new_vec = normalise((1-0.3)*old + 0.3*weight*post_vec)
        6. Writes updated vectors:
             SET user_vector:{user_id}  {text_vec, visual_vec}  EX 300
             Upserts Qdrant user_profiles (named vectors)
        7. LPUSH user_uas:{user_id}  "action:post_id"
           LTRIM user_uas:{user_id}  0 49
        8. ZADD online_users  {user_id: timestamp}
        9. INCR user_interaction_count:{user_id}
        10. Returns 200 {"status": "processed"}
```

### 1.3 User Requests Their Feed

```
Django FeedView calls signals_client or directly:
  → POST /feed  {user_id, limit}  to Rust engine
      Rust api.rs get_feed handler runs:

      HEARTBEAT (throttled):
        If last heartbeat > 60s ago:
          ZADD online_users {user_id: now+300}  (marks user online)
          Stored in in-memory heartbeat_cache (DashMap) to avoid Redis spam

      LEVEL 1 — Pre-computed push queue:
        LPOP feed:{user_id}  limit posts
        If found → feed_type = "push"

      LEVEL 2 — Real-time pipeline (if push queue empty):
        Loads user context:
          get_user_vectors(user_id)  → (text_vec 384-dim, visual_vec 512-dim)
          is_cold_start(user_id)     → bool (< 5 interactions)
          get_social_graph(user_id)  → (following_ids, blocked_ids) via Django API
        Builds ScoredPostsQuery with all context
        Runs PhoenixCandidatePipeline.execute():

          Phase 0 — Query Hydration:
            UserActionSeqQueryHydrator:
              ← BUG: uses hardcoded mock ["click","like"] if UAS missing
              Should load from user_store::get_action_sequence()

          Phase 1 — Candidate Retrieval (Sources):
            PhoenixSource (Qdrant ANN):
              Cold start → scroll text_meta_context, return newest posts
              Not cold  → search text_meta_context   with user text_vec  (3000)
                        → search image_meta_context  with user visual_vec (2000)
                        → search video_meta_context  with user visual_vec (2000)
              ← BUG: Qdrant point IDs are strings (post_id), Rust reads Num → always 0
            ThunderSource (in-network):
              For each following_id: LRANGE author_posts:{id} 0 49
              Up to 3000 candidates

          Phase 2 — Hydration:
            InNetworkCandidateHydrator:
              ← BUG: sets in_network=false for ALL, never checks following_ids
              ← BUG: never sets author_is_blocked from query.blocked_ids
            CoreDataCandidateHydrator: no-op
            VideoDurationCandidateHydrator: random 10% chance of video (mock)
            SubscriptionHydrator: no-op
            GizmoduckCandidateHydrator: no-op
            NeuralContextHydrator:
              GET neural_context:{tweet_id} from Redis
              Sets semantic_alignment_score and video_context

          Phase 3 — Filtering:
            ← BUG: in_network_only=false so filters ARE applied (correct)
            AgeFilter: uses Snowflake ID timestamp extraction
              ← BUG: tweet_ids are 0 (from Qdrant bug) → all fail age check
            SelfTweetFilter: removes viewer's own posts ✓
            PreviouslySeenPostsFilter: checks query.seen_ids
              ← BUG: seen_ids never loaded from Redis, always empty
            RetweetDeduplicationFilter: deduplicates retweets ✓
            AuthorSocialgraphFilter: checks author_is_blocked/muted
              ← BUG: never set to true (see hydrator bug above)
            MutedKeywordFilter: checks has_muted_keywords
              ← BUG: never set, always false
            VisibilityFilter: checks VisibilityReason::Unsafe ✓

          Phase 4 — Scoring:
            PhoenixScorer:
              ← BUG: assigns completely RANDOM scores (rand::gen_range)
              This is a placeholder — the model is not implemented
            WeightedScorer:
              Computes weighted sum of PhoenixScores
              Applies 20% boost for high semantic_alignment_score ✓
            AuthorDiversityScorer:
              Applies 0.8^(count-1) penalty per extra post from same author ✓

          Phase 5 — Selection:
            TopKScoreSelector:
              O(N) select_nth_unstable_by → top RESULT_SIZE (20) posts ✓

          Phase 6 — Side Effects:
            CacheRequestInfoSideEffect:
              SADD served_posts:{user_id}  all served post IDs
              EXPIRE served_posts:{user_id}  86400 ✓

      LEVEL 3 — Global Discovery fallback:
        Reads from in-memory discovery_cache (refreshed every 1s from Redis)
        Fills remaining slots if feed < limit

      Returns FeedResponse { request_id, feed, latency_ms, feed_type }
```

---

## Part 2 — Bugs (Complete List)

### BUG-01 🔴 CRITICAL — Qdrant Point ID Type Mismatch (Feed Returns Broken Data)

**Files:** `smart_ingestion/workers/text_worker.py`, `image_worker.py`, `aggregator.py`, `rust_feed_engine/src/sources.rs`

**Problem:** Python workers store Qdrant points using the string `post_id` as the point ID. Rust reads point IDs expecting `PointIdOptions::Num(n)` — a numeric u64. When it doesn't match, it falls to `_ => 0`, so every candidate comes out with `tweet_id: 0`. The entire feed is structurally broken — all posts appear to have the same ID, all fail the age filter, all get deduplicated into one.

**Fix — Python side:** All three workers must pass the integer post_id to Qdrant, not a string UUID.

In `text_worker.py`, `image_worker.py`, and `aggregator.py`, change `upsert_point` calls:
```python
# BEFORE
upsert_point(collection_name=..., point_id=post_id, ...)      # post_id is a string

# AFTER — post_id must be cast to int for Qdrant numeric ID
upsert_point(collection_name=..., point_id=int(post_id), ...)
```

Also update `qdrant_utils.py` to accept `int | str`:
```python
def upsert_point(
    collection_name: str,
    point_id: int | str,   # int preferred; str fallback for legacy
    vector: List[float],
    payload: Dict[str, Any],
) -> None:
    from qdrant_client.models import PointStruct
    init_qdrant_collection(collection_name, len(vector))
    client = get_qdrant_client()
    client.upsert(
        collection_name=collection_name,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )
```

**Fix — Rust side:** `sources.rs` already handles `PointIdOptions::Num(n)` — this will work correctly once Python stores integer IDs. No Rust change needed.

---

### BUG-02 🔴 CRITICAL — `InNetworkCandidateHydrator` Never Sets Blocked/Network Flags

**File:** `rust_feed_engine/src/hydrators.rs`

**Problem:** `InNetworkCandidateHydrator` sets `in_network = Some(false)` for every candidate regardless of `query.following_ids`. It never sets `author_is_blocked`. Downstream: `AuthorSocialgraphFilter` checks `author_is_blocked` but it's always `false`, so blocked users' posts are never removed.

**Fix — replace the entire hydrator implementation:**
```rust
pub struct InNetworkCandidateHydrator;

#[async_trait]
impl Hydrator for InNetworkCandidateHydrator {
    async fn hydrate(
        &self,
        query: &ScoredPostsQuery,
        mut candidates: Vec<PostCandidate>,
    ) -> Result<Vec<PostCandidate>, String> {
        let following: std::collections::HashSet<i64> =
            query.following_ids.iter().cloned().collect();
        let blocked: std::collections::HashSet<i64> =
            query.blocked_ids.iter().cloned().collect();

        for c in &mut candidates {
            c.in_network = Some(following.contains(&c.author_id));
            c.author_is_blocked = blocked.contains(&c.author_id);
            c.is_hydrated = true;
        }
        Ok(candidates)
    }
}
```

---

### BUG-03 🔴 CRITICAL — `seen_ids` Never Loaded; Users See Repeated Posts

**File:** `rust_feed_engine/src/api.rs`

**Problem:** `ScoredPostsQuery` is built with `seen_ids: vec![]` and `served_ids: vec![]` hardcoded (via `..Default::default()`). `PreviouslySeenPostsFilter` exists and checks `query.seen_ids`, but since it's always empty, posts are never filtered for having been seen. Users see the same posts on every feed refresh.

Note: `CacheRequestInfoSideEffect` correctly writes to `served_posts:{user_id}` — the data is being stored but never read back.

**Fix — in `api.rs` inside `get_feed`, after loading user vectors, add:**
```rust
// Load served post IDs to prevent re-serving
let served_ids: Vec<i64> = {
    let key = format!("served_posts:{}", user_id);
    redis_conn
        .smembers::<_, std::collections::HashSet<String>>(&key)
        .await
        .unwrap_or_default()
        .into_iter()
        .filter_map(|s| s.parse().ok())
        .collect()
};

// Then include in query:
let query = ScoredPostsQuery {
    served_ids,
    // ...
};
```

---

### BUG-04 🔴 CRITICAL — `PhoenixScorer` Uses Random Scores

**File:** `rust_feed_engine/src/scorers/phoenix_scorer.rs`

**Problem:** Every candidate receives purely random scores from `rand::gen_range`. This means the ranking has no intelligence whatsoever — the feed is random. This is explicitly marked as a placeholder but never replaced.

**This is the most important thing to fix before going public.**

Until a real ML model is integrated, replace with a deterministic heuristic scorer that uses real signals already available in the pipeline:

```rust
// Replace the random scorer with a signal-based heuristic:
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
                let network_boost = if c.in_network.unwrap_or(false) { 1.5 } else { 1.0 };

                // Alignment quality signal (from smart_ingestion)
                let alignment = c.semantic_alignment_score.unwrap_or(0.5).max(0.0);

                c.phoenix_scores = PhoenixScores {
                    // Map real signals to score fields WeightedScorer reads
                    favorite_score:  Some(alignment * 0.3),
                    click_score:     Some(freshness * 0.5),
                    dwell_time:      Some(freshness * network_boost * 60.0),
                    follow_author_score: if c.in_network.unwrap_or(false) { Some(1.0) } else { Some(0.0) },
                    ..Default::default()
                };

                c.last_scored_at_ms = Some(now_ms);
                c
            })
            .collect();

        Ok(scored)
    }
}
```

---

### BUG-05 🔴 CRITICAL — `UserActionSeqQueryHydrator` Uses Hardcoded Mock Data

**File:** `rust_feed_engine/src/extra_components.rs`

**Problem:** If the query's `user_action_sequence` is `None`, the hydrator replaces it with `vec!["click", "like"]` — hardcoded fake data. Every cold-start user (any user who hasn't explicitly set a UAS) gets the same fake action history. This should load the real sequence from Redis.

**Fix:** The query hydrator should read from `user_store::get_action_sequence()`. However, `QueryHydrator::hydrate` doesn't have access to Redis in the current trait signature. The correct fix is to load the action sequence alongside other user context in `api.rs` `get_feed`, then populate the query before it reaches the pipeline:

```rust
// In api.rs get_feed, add:
let action_sequence = user_store::get_action_sequence(user_id, 50, &mut redis_conn)
    .await
    .unwrap_or_default();

let query = ScoredPostsQuery {
    user_action_sequence: Some(UserActionSequence { actions: action_sequence }),
    // ...
};
```

Then remove the hardcoded fallback from `UserActionSeqQueryHydrator` entirely, or change it to a no-op.

---

### BUG-06 🟡 MAJOR — `AgeFilter` Rejects All Qdrant-Sourced Posts

**File:** `rust_feed_engine/src/filters/age_filter.rs`

**Problem:** `AgeFilter` uses `util::snowflake::duration_since_creation_opt(tweet_id)` which extracts a timestamp from the high bits of a Twitter Snowflake ID. Your post IDs are sequential integers from your own database — not Twitter Snowflake IDs. For a post with `tweet_id = 42`, the snowflake decoder reads the timestamp as `(42 >> 22) + TWITTER_EPOCH = 0 + 1288834974657ms`, which is a date in 2010. Every post appears to be 15 years old and gets filtered out.

**Fix — replace snowflake decoding with `created_at_ms` from the candidate:**
```rust
// In age_filter.rs:
impl AgeFilter {
    fn is_within_age(&self, candidate: &PostCandidate) -> bool {
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;

        if candidate.created_at_ms == 0 {
            return true; // No timestamp → don't filter
        }

        let age = std::time::Duration::from_millis(
            now_ms.saturating_sub(candidate.created_at_ms)
        );
        age <= self.max_age
    }
}

#[async_trait]
impl Filter for AgeFilter {
    async fn filter(
        &self,
        _query: &ScoredPostsQuery,
        candidates: Vec<PostCandidate>,
    ) -> Result<FilterResult<PostCandidate>, String> {
        let (kept, removed) = candidates
            .into_iter()
            .partition(|c| self.is_within_age(c));
        Ok(FilterResult { kept, removed })
    }
}
```

Also: the ingest handler sets `created_at_ms` to `now * 1000`. The Python workers need to include `created_at_ms` in the Qdrant payload and the Rust source needs to read it from the payload when constructing PostCandidate.

---

### BUG-07 🟡 MAJOR — `sources.rs` Never Reads `created_at_ms` from Payload

**File:** `rust_feed_engine/src/sources.rs`

**Problem:** Every `PostCandidate` constructed from Qdrant results sets `created_at_ms` using `SystemTime::now()` — the current time of the feed request, not the post creation time. This means every Qdrant-sourced post appears brand new regardless of when it was actually created.

**Fix — read `created_at_ms` from Qdrant payload:**
```rust
// Helper function — add to sources.rs:
fn extract_payload_i64(point: &ScoredPoint, key: &str) -> Option<i64> {
    point.payload.get(key)?.kind.as_ref().and_then(|k| match k {
        qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
        qdrant_client::qdrant::value::Kind::StringValue(s) => s.parse().ok(),
        _ => None,
    })
}

// When building PostCandidate from Qdrant result:
PostCandidate {
    tweet_id:       extract_payload_i64(&point, "post_id").unwrap_or(0),
    author_id:      extract_payload_i64(&point, "author_id").unwrap_or(0),
    created_at_ms:  extract_payload_i64(&point, "created_at_ms")
                        .map(|v| v as u64)
                        .unwrap_or_else(|| {
                            std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap()
                                .as_millis() as u64
                        }),
    ..Default::default()
}
```

Python workers must include `created_at_ms` in the Qdrant payload. Add to all three workers:
```python
import time
payload = {
    ...
    "created_at_ms": int(time.time() * 1000),
}
```

---

### BUG-08 🟡 MAJOR — `neural_context` Redis Cache Missing `embedding` for Image/Video

**File:** `smart_ingestion/workers/image_worker.py`, `aggregator.py`

**Problem:** `interaction_handler.rs` reads `neural_context:{post_id}` and looks for the `"embedding"` key to get the post vector for the EMA update. 

`text_worker.py` correctly stores `{"embedding": embedding, ...}`.

`image_worker.py` stores `{"type": "image", "object_tags": ..., "alignment_score": ..., "caption": ...}` — **no `embedding` key**.

`aggregator.py` stores `{"type": "video", "alignment_score": ..., ...}` — **no `embedding` key**.

Result: when a user likes an image or video post, the Rust interaction handler gets `None` for the embedding and returns `202 "pending ingestion"` — the user's visual interest vector never updates from image or video interactions.

**Fix — add embedding to image and video Redis cache:**

In `image_worker.py`:
```python
cache_neural_context(post_id, {
    "type": "image",
    "embedding": embedding,          # ADD THIS
    "object_tags": tags,
    "alignment_score": alignment,
    "caption": caption,
    "semantic_alignment_score": alignment,
})
```

In `aggregator.py`:
```python
cache_neural_context(post_id, {
    "type": "video",
    "embedding": final_vector,       # ADD THIS
    "alignment_score": alignment_score,
    "object_tags": object_tags,
    "transcript": transcript,
    "llava_description": summary_text,
    "yolo_tags": object_tags,
    "whisper_text": transcript,
    "semantic_alignment_score": alignment_score,
})
```

---

### BUG-09 🟡 MAJOR — `BloomFilter` Is a Non-Functional Stub

**File:** `rust_feed_engine/src/util.rs`

**Problem:** The `BloomFilter` struct is empty and `may_contain()` always returns `false`. The comment says "stub: always return false so we don't filter out things incorrectly". While this is safe, it means the `PreviouslySeenPostsFilter` relies entirely on `query.seen_ids` (a simple list), which doesn't scale. The bloom filter was meant to efficiently handle large sets of seen post IDs.

**Decision needed:** Either implement a real bloom filter (using the `bloom` crate) or remove the `BloomFilterEntry` from the model and the `bloom_filter_entries: Vec<BloomFilterEntry>` from `ScoredPostsQuery` since it's dead weight. For now, the `seen_ids` HashSet approach from `served_posts:{user_id}` Redis Set is sufficient. Remove the dead bloom filter code.

---

### BUG-10 🟠 MODERATE — `TopKScoreSelector` Ignores `payload.limit`

**File:** `rust_feed_engine/src/selectors.rs`

**Problem:** `TopKScoreSelector` always selects `params::RESULT_SIZE` (hardcoded 20) posts regardless of what `payload.limit` requested. The `/feed` endpoint accepts a `limit` parameter, puts it in the pipeline's `query`, but the selector ignores it.

**Fix:**
```rust
impl Selector for TopKScoreSelector {
    fn select(&self, query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>) -> Vec<PostCandidate> {
        // Use requested limit if provided, fall back to RESULT_SIZE
        let k = query.candidate_count
            .unwrap_or(params::RESULT_SIZE)
            .min(params::RESULT_SIZE) // cap at max
            .min(candidates.len());

        if k == 0 { return Vec::new(); }

        candidates.select_nth_unstable_by(k - 1, |a, b| {
            b.score.unwrap_or(f64::MIN)
                .partial_cmp(&a.score.unwrap_or(f64::MIN))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        candidates.truncate(k);
        candidates
    }
}
```

---

### BUG-11 🟠 MODERATE — `ingest_text.py` Prints to stdout in Production Code

**File:** `ingest_text.py`

**Problem:** `print(f"🚀 Starting text ingestion for post: {post_id}")` — raw `print` statements in a library module that gets imported by Django views. These emit to stdout in production, pollute logs, and can't be filtered by log level.

**Fix:** Replace all `print()` calls in `ingest_text.py` and `ingest_video.py` with `logging.getLogger(__name__).info(...)`.

---

### BUG-12 🟠 MODERATE — `get_image_embedding` Task Has No Retry Decorator

**File:** `smart_ingestion/workers/image_worker.py`

**Problem:** `get_image_embedding` is decorated with `@app.task` but has no `bind=True`, `max_retries`, or `default_retry_delay`. If this task fails mid-flight (network blip, model loading error), it fails permanently with no retry.

**Fix:** Add consistent retry configuration:
```python
@app.task(
    name="smart_ingestion.workers.image_worker.get_image_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def get_image_embedding(self, image_path: str) -> Dict:
    try:
        proc = get_processor()
        result = proc.process_image(image_path)
        return {"embedding": result["embedding"], "object_tags": result["object_tags"]}
    except Exception as exc:
        raise self.retry(exc=exc)
```

---

### BUG-13 🟠 MODERATE — `processor.py` Uses `__import__` Inside a Hot Loop

**File:** `smart_ingestion/ml_core/processor.py`

**Problem:** Inside `embed_video_frames`, every frame in the sampling loop calls:
```python
pil = Image.fromarray(
    __import__("cv2").cvtColor(frame, __import__("cv2").COLOR_BGR2RGB)
)
```
`__import__` inside a tight loop is an anti-pattern. Python caches module imports but `__import__` still has overhead from the lookup path and is unreadable.

**Fix:** Move `import cv2` to the top of the method (it's already imported elsewhere in the same method):
```python
def embed_video_frames(self, video_path: str) -> List[float]:
    if Path(video_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return self.embed_image(video_path)

    import cv2
    from PIL import Image
    # ... rest of method, use cv2 directly
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
```

---

### BUG-14 🟠 MODERATE — `test_description_quality.py` References Removed Models

**File:** `tests/test_description_quality.py`

**Problem:** The test file prints `"(This triggers YOLOv11, Whisper, and Video-LLaVA in parallel)"` and reads `parsed.get("llava_description")` expecting it to be a real language model description. LLaVA was removed and replaced with CLIP frame embeddings. The test references the old pipeline and gives misleading output.

**Fix:** Update the test to reflect the new pipeline — it should check for `alignment_score`, `object_tags`, and `transcript` instead of `llava_description`. Also update the comment.

---

## Part 3 — Security Audit

### SEC-01 🔴 CRITICAL — Rust Engine Has No Authentication

**File:** `rust_feed_engine/src/main.rs`, `api.rs`, `interaction_handler.rs`

**Problem:** The Rust engine exposes three unauthenticated endpoints:
- `POST /feed` — any caller can fetch any user's feed by setting `user_id`
- `POST /interaction` — any caller can manipulate any user's interest vectors
- `POST /ingest` — any caller can inject arbitrary posts into any user's feed

There is no API key, Bearer token, JWT validation, HMAC signature, or IP allowlist on any of these routes. This is a complete security hole if the engine is exposed beyond localhost.

**Fix — minimum viable protection (internal network key):**

Add to `rust_feed_engine/.env`:
```
INTERNAL_API_KEY=<generate with: openssl rand -hex 32>
```

Add middleware in `main.rs`:
```rust
use axum::middleware;
use axum::http::{Request, StatusCode};
use axum::middleware::Next;
use axum::response::Response;

async fn require_internal_key<B>(
    req: Request<B>,
    next: Next<B>,
) -> Result<Response, StatusCode> {
    let expected = std::env::var("INTERNAL_API_KEY").unwrap_or_default();
    let provided = req
        .headers()
        .get("X-Internal-Key")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if expected.is_empty() || provided == expected {
        Ok(next.run(req).await)
    } else {
        Err(StatusCode::UNAUTHORIZED)
    }
}

// In router:
let app = Router::new()
    .route("/health", get(api::health_check))
    .route("/feed", post(api::get_feed))
    .route("/ingest", post(api::ingest_event))
    .route("/interaction", post(interaction_handler::handle_interaction))
    .layer(middleware::from_fn(require_internal_key))
    .with_state(shared_state);
```

Add the same key to `signals_client.py`:
```python
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

def _headers():
    return {"X-Internal-Key": INTERNAL_API_KEY, "Content-Type": "application/json"}
```

---

### SEC-02 🔴 CRITICAL — No Input Validation on `/interaction` or `/ingest`

**Files:** `interaction_handler.rs`, `api.rs`

**Problem:**
- `user_id: i64` — accepts negative values, 0, and arbitrary integers
- `post_id: i64` — same
- `action: String` — partially validated (unknown actions return 400), but the string itself has no length limit
- `dwell_ms: Option<u64>` — accepts `u64::MAX` (292 years of dwell time)
- `/ingest` payload is `serde_json::Value` — completely untyped, accepts arbitrary JSON depth

A malicious caller could send `dwell_ms: 18446744073709551615` which, when used in any arithmetic, overflows. They could send deeply nested JSON payloads that exhaust memory during deserialisation.

**Fix — add validation in interaction handler:**
```rust
// At the top of handle_interaction:
if payload.user_id <= 0 || payload.post_id <= 0 {
    return (StatusCode::BAD_REQUEST, 
            Json(serde_json::json!({"error": "invalid user_id or post_id"}))).into_response();
}
if payload.action.len() > 32 {
    return (StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "action too long"}))).into_response();
}
if payload.dwell_ms.unwrap_or(0) > 3_600_000 {
    // Cap dwell at 1 hour
    // Either reject or clamp silently
}
```

---

### SEC-03 🟡 MAJOR — Secrets in `.env` Files Committed to Repository

**Files:** `rust_feed_engine/.env`, `smart_ingestion/.env`

**Problem:** Both `.env` files are in the repository with real configuration values. Even though they currently only contain `REDIS_URL` and `RUST_LOG`, the pattern is dangerous — it normalises committing env files and will eventually lead to real secrets (API keys, DB passwords) being committed.

**Fix:**
1. Add both files to `.gitignore` immediately
2. Rename them to `.env.example` with placeholder values
3. Add to `.gitignore`:
   ```
   .env
   .env.local
   rust_feed_engine/.env
   smart_ingestion/.env
   qdrant_storage/
   ```

---

### SEC-04 🟡 MAJOR — Path Traversal Risk in Media Processing

**Files:** `smart_ingestion/workers/image_worker.py`, `video_worker.py`, `aggregator.py`

**Problem:** File paths (`image_path`, `video_path`) are received from Celery task arguments and passed directly to `PIL.Image.open()`, `cv2.VideoCapture()`, and `faster_whisper`. A malicious or misconfigured caller could pass `../../etc/passwd` or an arbitrary file system path.

**Fix — validate file paths before processing:**
```python
import os
from pathlib import Path

ALLOWED_MEDIA_DIRS = ["/data/media", "/uploads", "/tmp"]  # configure to your setup

def validate_media_path(path: str) -> str:
    """Raise ValueError if path is outside allowed directories."""
    resolved = str(Path(path).resolve())
    if not any(resolved.startswith(d) for d in ALLOWED_MEDIA_DIRS):
        raise ValueError(f"Path {path!r} is outside allowed media directories")
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Media file not found: {resolved}")
    return resolved
```

Call `validate_media_path(image_path)` at the top of each worker task.

---

### SEC-05 🟡 MAJOR — `social_graph.rs` Internal Endpoint Has No Authentication

**File:** `rust_feed_engine/src/social_graph.rs`

**Problem:** The Rust engine calls `{BACKEND_URL}/internal/social-graph/{user_id}/` on your Django app. This endpoint returns sensitive social data (who follows whom, who is blocked). If the `/internal/` prefix isn't protected by network rules or an auth header, any client that can reach your Django server can enumerate social graphs for arbitrary user IDs.

**Fix — add shared secret validation to the Django internal endpoint:**
```python
# In Django:
INTERNAL_SECRET = os.environ.get("INTERNAL_API_KEY")

class InternalSocialGraphView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, user_id):
        provided = request.headers.get("X-Internal-Key", "")
        if not INTERNAL_SECRET or provided != INTERNAL_SECRET:
            return Response(status=401)
        # ... rest of view
```

And in `social_graph.rs`, pass the key:
```rust
let response = http_client
    .get(&url)
    .header("X-Internal-Key", std::env::var("INTERNAL_API_KEY").unwrap_or_default())
    .timeout(Duration::from_millis(200))
    .send()
    .await?;
```

---

### SEC-06 🟠 MODERATE — No Rate Limiting on `/interaction`

**Problem:** A single client can call `POST /interaction` thousands of times per second to manipulate another user's interest vectors arbitrarily. Without rate limiting, this is a trivial user profiling attack.

**Fix — add a per-user rate limit using Redis:**
```rust
// At the top of handle_interaction, before processing:
let rate_key = format!("ratelimit:interaction:{}", payload.user_id);
let count: u64 = redis_conn.incr(&rate_key, 1).await.unwrap_or(0);
if count == 1 {
    let _: () = redis_conn.expire(&rate_key, 60).await.unwrap_or(());
}
if count > 120 {  // max 120 interactions per minute per user
    return (StatusCode::TOO_MANY_REQUESTS,
            Json(serde_json::json!({"error": "rate limit exceeded"}))).into_response();
}
```

---

### SEC-07 🟠 MODERATE — `docker-compose.yml` Exposes Qdrant Ports to Host

**File:** `docker-compose.yml`

**Problem:** Qdrant is exposed on `0.0.0.0:6333` and `0.0.0.0:6334` (gRPC). In any deployment where the server is not behind a firewall, this means Qdrant is publicly accessible on the internet — anyone can read, write, or delete your vector collections.

**Fix:**
```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports:
    - "127.0.0.1:6333:6333"   # bind to localhost only
    - "127.0.0.1:6334:6334"
```

Same for Redis — change `"6379:6379"` to `"127.0.0.1:6379:6379"`.

---

## Part 4 — Clean Code Issues

### CC-01 — Dead Imports in Workers

**File:** `smart_ingestion/workers/text_worker.py`, `image_worker.py`, `aggregator.py`

`import uuid` is present in all three but never used after the fix where `post_id` is used directly as the Qdrant point ID. Remove the unused imports.

---

### CC-02 — `uuid` Import Removed But BM25Filter Import Unused in Prod

**File:** `smart_ingestion/workers/text_worker.py`

`BM25Filter` is imported at the module level but only used in the `bm25_prefilter` utility function. This means every text worker process imports and initialises `rank_bm25` unnecessarily. Move the import inside `bm25_prefilter`:
```python
def bm25_prefilter(query_text, candidate_texts, top_k=None):
    from smart_ingestion.ml_core.bm25_filter import BM25Filter  # lazy import
    k = top_k or settings.BM25_TOP_K
    f = BM25Filter(corpus=candidate_texts)
    return f.top_k(query=query_text, k=k)
```

---

### CC-03 — `pipeline.rs` Has Inconsistent Whitespace (Empty Lines in Code Blocks)

**File:** `rust_feed_engine/src/pipeline.rs`

The `execute` method has excessive empty lines between nearly every statement — a sign of either manual formatting or an IDE issue. It makes the code hard to read. This should be cleaned with `cargo fmt`.

**Action:** Run `cargo fmt` in the `rust_feed_engine/` directory. This fixes all Rust formatting in one command.

---

### CC-04 — `params.rs` Uses Magic Numbers Without Explanation

**File:** `rust_feed_engine/src/params.rs`

Weights like `REPLY_WEIGHT: f64 = 27.0` and `CLICK_WEIGHT: f64 = 12.0` have a comment saying "Hypothetical weights based on public analysis" but no source cited and no explanation for why reply is worth 54× a like. For a public codebase these need either a doc comment explaining the reasoning or a link to the analysis they're based on.

Add a block comment above the weights:
```rust
// Scoring weights reflect the relative value of each engagement signal.
// Reply (27.0) ranks highest because it requires the most effort and
// most strongly indicates content resonance. Values are derived from
// public analysis of Twitter's open-sourced ranking model.
// These should be tuned via A/B testing once real engagement data exists.
```

---

### CC-05 — `util.rs` Snowflake Module Will Never Be Used Correctly

**File:** `rust_feed_engine/src/util.rs`

The `snowflake` module decodes Twitter's proprietary ID format. Your system doesn't use Twitter Snowflake IDs. After fixing BUG-06 (AgeFilter using `created_at_ms`), the snowflake module becomes completely dead code. Remove it to avoid confusion.

```rust
// Remove the entire snowflake module from util.rs
// Remove the import from age_filter.rs: use crate::util::snowflake;
```

---

### CC-06 — `hydrators.rs` Mock Hydrators Should Be Clearly Labelled

**File:** `rust_feed_engine/src/hydrators.rs`

`CoreDataCandidateHydrator`, `SubscriptionHydrator`, and `GizmoduckCandidateHydrator` are all no-ops — they return candidates unchanged. They exist as stubs for future implementation. A developer reading the code has no way to know whether these are intentionally empty or accidentally incomplete.

Add a `// TODO:` comment explaining what each should do:
```rust
pub struct CoreDataCandidateHydrator;
// TODO: Hydrate with post text, media URLs, and like/reply counts from your DB.
// Called before scoring so scorers have full content data.

pub struct SubscriptionHydrator;
// TODO: Check if candidate requires a subscription the viewer doesn't have.
// Set candidate.visibility_reason = Some(VisibilityReason::Unsafe) if paywalled.

pub struct GizmoduckCandidateHydrator;
// TODO: Hydrate with author profile data (display name, avatar, verification).
// Currently handled client-side; populate if feed response should include author info.
```

---

### CC-07 — `requirements.txt` Contains Unrelated Dependencies

**File:** `requirements.txt` (root)

The root requirements file contains `chess`, `python-chess`, `pygame`, `paypalrestsdk`, `matplotlib`, `seaborn`, and other packages that have absolutely nothing to do with a feed algorithm. This is clearly a dump of the entire project's dependencies. For a public repository, this should be split:

```
requirements/
  base.txt        # Django, DRF, Redis, Celery basics
  ml.txt          # smart_ingestion ML deps (torch, transformers, etc.)
  dev.txt         # testing, benchmarking tools
```

---

### CC-08 — `signals_client.py` Is at Wrong Level

**File:** `signals_client.py` (root)

This file is at the repository root but it's a Django/app utility — it should live inside the Django app or at minimum in a `client/` directory. At the root it looks like an entry point, which it isn't. Move to `clients/signals_client.py` or into the Django app directory.

---

### CC-09 — `test_description_quality.py` Has a 10-Minute Blocking `task.get(timeout=600)`

**File:** `tests/test_description_quality.py`

The test calls `task.get(timeout=600)` — a 10-minute blocking wait. If the Celery worker is not running, the test hangs silently for 10 minutes before failing. Replace with:
```python
try:
    result = task.get(timeout=120, propagate=True)
except Exception as e:
    print(f"Task failed or timed out after 120s: {e}")
    return
```

---

## Part 5 — Optimisation Opportunities

### OPT-01 — `get_qdrant_client()` Creates a New Connection Every Call

**File:** `smart_ingestion/utils/qdrant_utils.py`

`get_qdrant_client()` is called on every `upsert_point()` and `search_similar()` — it creates a new `QdrantClient` instance each time, which means a new HTTP connection per call. Under high throughput this creates unnecessary overhead.

**Fix — module-level singleton:**
```python
_qdrant_client = None

def get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        from smart_ingestion.config import settings
        _qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    return _qdrant_client
```

---

### OPT-02 — `NeuralContextHydrator` Makes N Sequential Redis Calls

**File:** `rust_feed_engine/src/hydrators.rs`

`NeuralContextHydrator` loops over every candidate and does one `GET neural_context:{tweet_id}` per candidate. For 7,000 candidates that's 7,000 sequential Redis round-trips.

**Fix — use Redis pipeline to batch all GETs:**
```rust
impl Hydrator for NeuralContextHydrator {
    async fn hydrate(&self, _query: &ScoredPostsQuery, mut candidates: Vec<PostCandidate>)
        -> Result<Vec<PostCandidate>, String>
    {
        use redis::AsyncCommands;
        let mut conn = self.redis.clone();
        let keys: Vec<String> = candidates.iter()
            .map(|c| format!("neural_context:{}", c.tweet_id))
            .collect();

        // Single pipelined MGET instead of N sequential GETs
        let values: Vec<Option<String>> = redis::cmd("MGET")
            .arg(&keys)
            .query_async(&mut conn)
            .await
            .unwrap_or_else(|_| vec![None; candidates.len()]);

        for (c, raw) in candidates.iter_mut().zip(values.iter()) {
            if let Some(data) = raw {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(data) {
                    c.semantic_alignment_score = json["semantic_alignment_score"].as_f64();
                    c.video_context = json["llava_description"].as_str().map(String::from);
                }
            }
        }
        Ok(candidates)
    }
}
```

This reduces 7,000 Redis round-trips to 1.

---

### OPT-03 — Celery `warmup_models` Loads Only Text Models

**File:** `smart_ingestion/celery_app.py`

The warmup signal calls `embed_text` and `text_to_clip_vector` but not `_get_yolo()` or `_get_whisper()`. Workers on the image and video queues will still have cold-start latency on their first task.

**Fix:** Trigger all relevant model loads based on which queues the worker is serving. Or simplify — always warm all models since they're shared in the singleton:
```python
@worker_ready.connect
def warmup_models(sender, **kwargs):
    log = logging.getLogger(__name__)
    log.info("Warming up ML models...")
    from smart_ingestion.ml_core.processor import get_processor
    proc = get_processor()
    proc.embed_text("warmup")           # MiniLM
    proc.text_to_clip_vector("warmup")  # CLIP text
    # Warm image path — requires a dummy image
    import numpy as np
    from PIL import Image
    dummy = Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8))
    proc._clip_image_embed(dummy)       # CLIP vision
    proc._get_yolo()                    # YOLOv8n
    proc._get_whisper()                 # faster-whisper
    log.info("All models warm — worker ready.")
```

---

### OPT-04 — Discovery Cache Refresh Is Too Frequent

**File:** `rust_feed_engine/src/main.rs`

The background task refreshes the in-memory `discovery_cache` every 1 second:
```rust
let mut interval = tokio::time::interval(std::time::Duration::from_secs(1));
```

This means 60 Redis `LRANGE` calls per minute reading up to 100 posts. For a discovery cache that changes only when new posts are ingested, a 30-second or even 60-second refresh interval is adequate and reduces Redis load by 30-60×.

**Fix:** Change to `from_secs(30)`. Alternatively, use a Redis pub/sub channel to trigger cache invalidation only when new content is ingested.

---

## Part 6 — Summary of All Actions Required

### Do First (Bugs That Break Core Functionality)

| # | File(s) | Action |
|---|---------|--------|
| BUG-01 | Python workers + `qdrant_utils.py` | Store integer post_id as Qdrant point ID |
| BUG-02 | `hydrators.rs` | Set `in_network` and `author_is_blocked` from query sets |
| BUG-03 | `api.rs` | Load `served_ids` from Redis before building query |
| BUG-04 | `phoenix_scorer.rs` | Replace random scores with deterministic heuristics |
| BUG-05 | `api.rs` + `extra_components.rs` | Load real action sequence from Redis |
| BUG-06 | `age_filter.rs` | Use `created_at_ms` instead of snowflake decoding |
| BUG-07 | `sources.rs` + Python workers | Read and store `created_at_ms` in Qdrant payload |
| BUG-08 | `image_worker.py` + `aggregator.py` | Add `embedding` to Redis neural_context cache |

### Do Second (Security Before Going Public)

| # | File(s) | Action |
|---|---------|--------|
| SEC-01 | `main.rs` | Add internal API key middleware to all endpoints |
| SEC-02 | `interaction_handler.rs` | Add input validation (bounds, lengths) |
| SEC-03 | `.gitignore` + both `.env` files | Remove `.env` files from repo, add to `.gitignore` |
| SEC-04 | All Python workers | Add `validate_media_path()` before processing |
| SEC-05 | `social_graph.rs` + Django | Add shared secret to internal social graph endpoint |
| SEC-06 | `interaction_handler.rs` | Add per-user rate limiting via Redis |
| SEC-07 | `docker-compose.yml` | Bind Redis and Qdrant to `127.0.0.1` only |

### Do Third (Clean Code for Public Readability)

| # | File(s) | Action |
|---|---------|--------|
| CC-01 | Workers | Remove unused `uuid` imports |
| CC-02 | `text_worker.py` | Lazy-import BM25Filter |
| CC-03 | `pipeline.rs` | Run `cargo fmt` |
| CC-04 | `params.rs` | Add explanatory comments to weights |
| CC-05 | `util.rs` + `age_filter.rs` | Remove dead snowflake module |
| CC-06 | `hydrators.rs` | Add TODO comments to stub hydrators |
| CC-07 | `requirements.txt` | Split into base/ml/dev requirement files |
| CC-08 | `signals_client.py` | Move to `clients/` directory |
| CC-09 | `test_description_quality.py` | Fix 10-minute blocking timeout + update for new pipeline |
| CC-10 | `test_description_quality.py` | Remove references to LLaVA (model no longer used) |

### Do Fourth (Performance)

| # | File(s) | Action |
|---|---------|--------|
| OPT-01 | `qdrant_utils.py` | Singleton Qdrant client |
| OPT-02 | `hydrators.rs` | Batch Redis GET with MGET pipeline |
| OPT-03 | `celery_app.py` | Warm all models on startup |
| OPT-04 | `main.rs` | Increase discovery cache refresh interval to 30s |
