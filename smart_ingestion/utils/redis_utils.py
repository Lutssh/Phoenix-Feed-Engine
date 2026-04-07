"""
utils/redis_utils.py
─────────────────────
Redis helpers for the neural context cache.
Cache key format: neural_context:{post_id}
TTL: 24 hours (configurable via settings.CACHE_TTL_SECONDS)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_redis_client():
    import redis
    from smart_ingestion.config import settings
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def cache_neural_context(post_id: str, context: Dict[str, Any]) -> bool:
    """
    Store neural context for a post in Redis.
    Returns True on success, False on failure (fail-safe — never raises).
    """
    from smart_ingestion.config import settings
    try:
        r = get_redis_client()
        key = f"neural_context:{post_id}"
        r.set(key, json.dumps(context), ex=settings.CACHE_TTL_SECONDS)
        return True
    except Exception as exc:
        logger.warning("Redis cache write failed for %s: %s", post_id, exc)
        return False


def get_neural_context(post_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached neural context for a post.
    Returns None on cache miss or Redis error.
    """
    try:
        r = get_redis_client()
        raw = r.get(f"neural_context:{post_id}")
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("Redis cache read failed for %s: %s", post_id, exc)
        return None


def invalidate_context(post_id: str) -> None:
    """Delete cached context for a post (e.g. after content update)."""
    try:
        get_redis_client().delete(f"neural_context:{post_id}")
    except Exception:
        pass
