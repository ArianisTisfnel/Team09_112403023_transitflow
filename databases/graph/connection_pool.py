"""
Neo4j connection pool — Stage 3.3 stub.

This is a temporary placeholder so `from databases.graph.connection_pool import get_pool`
does not raise ModuleNotFoundError during Stage 1-2 development.

The real implementation (LRU-managed Neo4j driver with max 10 connections) is built
in Stage 3.3 and will overwrite this file.

Unit tests should patch `databases.graph.queries.get_pool` with a MagicMock.
Integration tests run only after the real connection_pool.py is in place.
"""

from __future__ import annotations


class _StubPool:
    """Placeholder pool object. Mimics the context-manager interface of neo4j.Driver."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def session(self, **kwargs):
        raise RuntimeError(
            "Real Neo4j connection not yet configured (stub pool). "
            "Stage 3.3 must be completed before integration tests can run."
        )


_pool: _StubPool | None = None


def get_pool() -> "_StubPool":
    """Return the (stub) Neo4j connection pool. Replaced by real implementation in Stage 3.3."""
    global _pool
    if _pool is None:
        _pool = _StubPool()
    return _pool
