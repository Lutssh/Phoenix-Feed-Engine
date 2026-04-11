// rust_feed_engine/src/user_store.rs
use crate::interaction_weights::COLD_START_THRESHOLD;
use anyhow::Result;
use qdrant_client::qdrant::vectors_output::VectorsOptions;
use qdrant_client::qdrant::{GetPointsBuilder, PointId, PointStruct, UpsertPointsBuilder};
use qdrant_client::{Payload, Qdrant};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UserVectors {
    pub text_vector: Vec<f64>,
    pub visual_vector: Vec<f64>,
    pub updated_at: u64,
}

pub async fn get_user_vectors(
    user_id: i64,
    redis: &mut redis::aio::ConnectionManager,
    qdrant: &Qdrant,
) -> Result<(Vec<f64>, Vec<f64>)> {
    let key = format!("user_vector:{}", user_id);

    // 1. Try Redis Hot Cache
    if let Ok(Some(cached)) = redis.get::<_, Option<String>>(&key).await {
        if let Ok(vecs) = serde_json::from_str::<UserVectors>(&cached) {
            return Ok((vecs.text_vector, vecs.visual_vector));
        }
    }

    // 2. Fallback to Qdrant user_profiles
    let point_id: PointId = (user_id as u64).into();
    let response = qdrant
        .get_points(GetPointsBuilder::new("user_profiles", vec![point_id]).with_vectors(true))
        .await?;

    if let Some(point) = response.result.first() {
        if let Some(vectors) = &point.vectors {
            if let Some(VectorsOptions::Vectors(named_vectors)) = &vectors.vectors_options {
                #[allow(deprecated)]
                let text_vec: Option<Vec<f64>> = named_vectors
                    .vectors
                    .get("text_vector")
                    .map(|v| v.data.iter().map(|&x| x as f64).collect());

                #[allow(deprecated)]
                let visual_vec: Option<Vec<f64>> = named_vectors
                    .vectors
                    .get("visual_vector")
                    .map(|v| v.data.iter().map(|&x| x as f64).collect());

                if let (Some(t), Some(v)) = (text_vec, visual_vec) {
                    // Update Redis cache
                    let vecs = UserVectors {
                        text_vector: t.clone(),
                        visual_vector: v.clone(),
                        updated_at: chrono::Utc::now().timestamp() as u64,
                    };
                    let _: () = redis
                        .set_ex(&key, serde_json::to_string(&vecs)?, 300)
                        .await?;
                    return Ok((t, v));
                }
            }
        }
    }

    // 3. Cold Start - Return zero vectors
    Ok((vec![0.0; 384], vec![0.0; 512]))
}

pub async fn set_user_vectors(
    user_id: i64,
    text_vector: Vec<f64>,
    visual_vector: Vec<f64>,
    redis: &mut redis::aio::ConnectionManager,
    qdrant: &Qdrant,
) -> Result<()> {
    let key = format!("user_vector:{}", user_id);
    let vecs = UserVectors {
        text_vector: text_vector.clone(),
        visual_vector: visual_vector.clone(),
        updated_at: chrono::Utc::now().timestamp() as u64,
    };

    // 1. Write to Redis (Hot)
    let _: () = redis
        .set_ex(&key, serde_json::to_string(&vecs)?, 300)
        .await?;

    // 2. Write to Qdrant (Durable)
    let point_id: PointId = (user_id as u64).into();
    let mut vectors = std::collections::HashMap::new();
    vectors.insert(
        "text_vector".to_string(),
        text_vector.iter().map(|&x| x as f32).collect::<Vec<f32>>(),
    );
    vectors.insert(
        "visual_vector".to_string(),
        visual_vector
            .iter()
            .map(|&x| x as f32)
            .collect::<Vec<f32>>(),
    );

    qdrant
        .upsert_points(UpsertPointsBuilder::new(
            "user_profiles",
            vec![PointStruct::new(point_id, vectors, Payload::new())],
        ))
        .await?;

    Ok(())
}

pub fn ema_update(old_vec: &[f64], interaction_vec: &[f64], weight: f64, alpha: f64) -> Vec<f64> {
    assert_eq!(old_vec.len(), interaction_vec.len());

    let updated: Vec<f64> = old_vec
        .iter()
        .zip(interaction_vec.iter())
        .map(|(old, new)| (1.0 - alpha) * old + alpha * weight * new)
        .collect();

    l2_normalise(&updated)
}

pub fn l2_normalise(vec: &[f64]) -> Vec<f64> {
    let norm: f64 = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
    if norm < 1e-10 {
        return vec.to_vec();
    }
    vec.iter().map(|x| x / norm).collect()
}

pub async fn get_action_sequence(
    user_id: i64,
    limit: usize,
    redis: &mut redis::aio::ConnectionManager,
) -> Result<Vec<String>> {
    let key = format!("user_uas:{}", user_id);
    let actions: Vec<String> = redis.lrange(key, 0, (limit as isize) - 1).await?;
    Ok(actions)
}

pub async fn append_action(
    user_id: i64,
    action: &str,
    post_id: i64,
    redis: &mut redis::aio::ConnectionManager,
) -> Result<()> {
    let key = format!("user_uas:{}", user_id);
    let value = format!("{}:{}", action, post_id);
    let _: () = redis.lpush(&key, &value).await?;
    let _: () = redis.ltrim(&key, 0, 49).await?;
    let _: () = redis.expire(&key, 3600).await?;
    Ok(())
}

pub async fn increment_interaction_count(
    user_id: i64,
    redis: &mut redis::aio::ConnectionManager,
) -> Result<()> {
    let key = format!("user_interaction_count:{}", user_id);
    let _: () = redis.incr(key, 1).await?;
    Ok(())
}

pub async fn is_cold_start(
    user_id: i64,
    redis: &mut redis::aio::ConnectionManager,
) -> Result<bool> {
    let key = format!("user_interaction_count:{}", user_id);
    let count: u64 = redis.get(key).await.unwrap_or(0);
    Ok(count < COLD_START_THRESHOLD)
}
