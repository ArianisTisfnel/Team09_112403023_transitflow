"""
TransitFlow — Neo4j Connection Pool
=====================================
Wraps the Neo4j driver in a module-level singleton configured with
max_connection_pool_size=10, replacing the per-query driver creation
pattern in databases/graph/queries.py.

Usage (drop-in for the old `with _driver() as driver:` pattern):

    with get_pool() as driver:
        with driver.session() as session:
            result = session.run(...)
"""

# TASK 6 EXTENSION: Neo4j connection pool (driver singleton). See TASK6.md + DESIGN_DOC §7.

from __future__ import annotations

import logging

from neo4j import Driver, GraphDatabase, Session

from skeleton.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)

MAX_POOL_SIZE = 10


class Neo4jConnectionPool:
    """
    Thin wrapper over neo4j.Driver that enforces a fixed max_pool_size.

    The underlying neo4j.Driver already manages an internal connection pool;
    this class configures it at construction time and exposes a context-manager
    interface that is compatible with the existing `with _driver() as driver:`
    call sites — without closing the pool on exit.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        max_pool_size: int = MAX_POOL_SIZE,
    ) -> None:
        self._driver: Driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_pool_size,
        )
        self._max_pool_size = max_pool_size
        logger.info(
            "Neo4jConnectionPool initialised  uri=%s  max_pool_size=%d",
            uri,
            max_pool_size,
        )

    # ── Context-manager interface ──────────────────────────────────────────────

    def __enter__(self) -> Neo4jConnectionPool:
        return self

    def __exit__(self, *_) -> None:
        pass  # Pool stays alive; individual sessions close via their own __exit__

    # ── Session factory ────────────────────────────────────────────────────────

    def session(self, **kwargs) -> Session:
        """Acquire a session from the pool. Use as a context manager."""
        return self._driver.session(**kwargs)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._driver.close()
        logger.info("Neo4jConnectionPool closed")

    def __del__(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass


# ── Module-level singleton ─────────────────────────────────────────────────────

_pool: Neo4jConnectionPool | None = None


def get_pool() -> Neo4jConnectionPool:
    """Return the shared connection pool, initialising it on first call."""
    global _pool
    if _pool is None:
        _pool = Neo4jConnectionPool(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=NEO4J_PASSWORD,
            max_pool_size=MAX_POOL_SIZE,
        )
    return _pool
