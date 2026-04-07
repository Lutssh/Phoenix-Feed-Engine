# X "For You" Feed Algorithm Analysis

## 1. Executive Summary

The "For You" feed is a sophisticated recommendation system that blends **In-Network** content (people you follow) with **Out-of-Network** content (discovered via machine learning). The core differentiator is its reliance on **Phoenix**, a Grok-based transformer model, which treats user engagement history as a language modeling problem to predict future interactions.

Unlike traditional systems that rely heavily on hand-crafted features (e.g., "is this post a video?", "does the user like sports?"), this system uses raw user action sequences and embeddings, allowing the model to learn complex, non-linear patterns of interest automatically.

## 2. The Pipeline Architecture

The system is orchestrated by the `Home Mixer` service, which executes a linear pipeline for every request.

### Phase 1: Context Gathering (Query Hydration)
Before looking for tweets, the system builds a context of *who you are* right now.
- **User Action Sequence (UAS)**: Fetches your recent history—likes, replies, retweets, profile clicks. This is the primary input for the ML model.
- **User Features**: Fetches your "graph" (who you follow, who you block) and other user-level metadata.

### Phase 2: Candidate Sourcing
The system retrieves potential tweets to show you from two main engines:
1.  **Thunder (In-Network)**: An in-memory, real-time engine that serves recent tweets from accounts you explicitly follow. It ensures you don't miss updates from your circle.
2.  **Phoenix Retrieval (Out-of-Network)**: A "Two-Tower" neural network that finds relevant content from the entire global conversation. It embeds your interests and finds tweets with similar embeddings, even from people you don't follow.

### Phase 3: Hydration & Enrichment
Raw tweet IDs are "hydrated" with rich metadata:
- **Core Data**: Text, images, video URLs.
- **User Profiles**: Author names, verification status (Blue check), avatar URLs (via "Gizmoduck").
- **Social Context**: "Did I already like this?", "Am I blocked by this author?"

### Phase 4: Filtering (The "Safety & Quality" Layer)
A series of strict filters removes ineligible content:
- **Basic Hygiene**: `DropDuplicates`, `SelfTweetFilter` (don't show me my own tweets).
- **Fatigue Control**: `PreviouslySeenPosts` and `PreviouslyServedPosts` ensure you don't see the same thing twice.
- **Safety**: `AuthorSocialgraphFilter` respects your blocks and mutes. `MutedKeywordFilter` hides content with words you've muted.
- **Access**: `IneligibleSubscriptionFilter` hides paywalled content you don't have access to.

### Phase 5: Scoring (The Brain)
This is where the ranking magic happens. Candidates are scored sequentially:

1.  **Phoenix Scorer (The Heavy Lifter)**:
    -   **Model**: A Grok-based Transformer.
    -   **Input**: `[User Embedding] + [Your History] + [Candidate Tweet]`.
    -   **Mechanism**: The model attends to your history to understand your current "vibe" and predicts the probability of you taking specific actions on the candidate tweet.
    -   **Predictions**: It outputs probabilities for multiple actions: `P(Like)`, `P(Reply)`, `P(Repost)`, `P(Click)`, `P(Negative Feedback)`, etc.

2.  **Weighted Scorer**:
    -   Combines the raw probabilities into a single score using a weighted sum.
    -   *Positive weights*: Likes, Reposts, Replies increase score.
    -   *Negative weights*: Blocks, Mutes, "Show less often" drastically reduce score.
    -   *Note*: Exact weights are kept secret in `params.rs`, but the mechanism is transparent.

3.  **Author Diversity Scorer**:
    -   Down-weights tweets if you have already seen too many from the same author in this batch. Prevents one active user from dominating your feed.

4.  **OON Scorer**:
    -   Applies specific adjustments for Out-Of-Network content, likely to balance the mix between familiar and discovery content.

### Phase 6: Selection & Final Polish
- **Selection**: The top K tweets with the highest scores are selected.
- **Visibility Filtering (VF)**: A final check against a sophisticated trust & safety engine to catch and remove illegal, violent, or spammy content that might have slipped through.
- **Conversation Dedup**: Ensures you don't see multiple parts of the same conversation thread disjointedly.

## 3. Key Technical Innovations

### Candidate Isolation
In standard Transformers, all inputs attend to all other inputs. In Phoenix, **candidates cannot attend to each other**. They can only attend to the User History.
-   *Why?* This ensures the score of Tweet A doesn't change just because Tweet B is next to it in the batch. This makes scoring deterministic and cacheable.

### "Grok" as a Recommender
The system repurposes a Large Language Model (LLM) architecture for recommendation. Instead of predicting the next word, it predicts the "next action" you will take. This treats user behavior as a language, allowing it to capture nuance ("User likes tech news in the morning but funny memes at night") better than rigid statistical models.

### Real-Time Ingestion (Thunder)
Thunder allows X to serve tweets milliseconds after they are posted. It bypasses traditional database read lag by keeping active users' timelines in RAM, ensuring the "For You" feed feels instantaneous and live.
