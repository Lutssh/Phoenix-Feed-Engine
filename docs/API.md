# Feed Engine API Documentation

## Integration Contract

The Feed Engine acts as a standalone microservice. Clients (e.g., the API Gateway or Frontend Backend-for-Frontend) interact with it via HTTP.

### 1. Requesting a Feed
**Endpoint**: `POST /feed`
**Content-Type**: `application/json`

This endpoint triggers the full recommendation pipeline: Retrieval -> Hydration -> Scoring -> Ranking.

#### Request Payload
```json
{
  "user_id": 12345,       // Integer (i64): The ID of the user requesting the feed
  "limit": 50,            // Integer (Optional): Number of posts to return (default: 20)
  "cursor": "token_str"   // String (Optional): Pagination token for infinite scroll
}
```

#### Success Response (200 OK)
```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "latency_ms": 45,
  "feed": [
    {
      "tweet_id": 987654321,
      "author_id": 55555,
      "score": 12.5,
      "phoenix_scores": {
        "favorite_score": 0.85,   // Predicted probability of a Like
        "retweet_score": 0.12,    // Predicted probability of a Retweet
        "reply_score": 0.05,      // Predicted probability of a Reply
        "dwell_time": 4.5         // Predicted time user will spend on post (seconds)
      },
      "visibility_reason": "Safe",
      "is_hydrated": true
    },
    // ... more candidates
  ]
}
```

#### Error Responses
*   **422 Unprocessable Entity**: Invalid JSON format or type mismatch (e.g., string `user_id` instead of integer).
*   **500 Internal Server Error**: Database connection failure or pipeline panic.

---

### 2. Ingesting Events
**Endpoint**: `POST /ingest`
**Content-Type**: `application/json`

This endpoint is used for "Fan-out on Write" or updating real-time user state (e.g., updating the user's vector embedding immediately after they like a post).

#### Request Payload
```json
{
  "event_type": "post_created", // String: Discriminator for the event logic
  "user_id": 12345,             // Integer: The actor who performed the event
  "payload": {                  // Object: Arbitrary JSON specific to the event type
    "tweet_id": 987654321,
    "text": "Hello world",
    "tags": ["rust", "system-design"]
  }
}
```

#### Success Response (202 Accepted)
```text
Event Queued
```

---

### 3. Health Check
**Endpoint**: `GET /health`

Used by load balancers (Kubernetes/AWS) to verify the service is ready to accept traffic.

#### Success Response (200 OK)
```text
Service is healthy
```
