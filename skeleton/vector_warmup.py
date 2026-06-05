"""
TransitFlow — Vector Cache Warmup
===================================
Pre-loads the top 50 frequently-accessed policy documents into
policy_cache at system startup to reduce cold-start latency for
policy Q&A queries.
"""

from __future__ import annotations

import logging

import psycopg2
import psycopg2.extras

from skeleton.cache import policy_cache
from skeleton.config import PG_DSN

logger = logging.getLogger(__name__)

TOP_K_WARMUP = 50


def warmup_policy_cache() -> int:
    """
    Load the top TOP_K_WARMUP policy documents from policy_documents into
    policy_cache.  Should be called once at system startup.

    Cache key format: "policy:{id}"

    Returns:
        Number of documents successfully loaded into the cache.
    """
    try:
        with psycopg2.connect(PG_DSN) as conn:
            conn.autocommit = True
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, title, category, content
                    FROM policy_documents
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (TOP_K_WARMUP,),
                )
                rows = cur.fetchall()

        count = 0
        for row in rows:
            cache_key = f"policy:{row['id']}"
            policy_cache.set(cache_key, dict(row))
            count += 1

        print(f"已成功快取 {count} 份政策文件")
        logger.info("Policy warmup complete: %d documents cached", count)
        return count

    except Exception as exc:
        logger.warning("Policy warmup failed (system will continue): %s", exc)
        print(f"政策文件預熱失敗（系統繼續啟動）: {exc}")
        return 0
