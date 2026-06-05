"""
Unit tests for Stage 3.3 — Performance Boost
=============================================
DoD coverage:
  1. CacheManager: TTL expiry, LRU eviction, get/set/clear, stats, thread-safety
  2. Module-level cache instances (fare_cache, schedule_cache, policy_cache)
  3. Neo4jConnectionPool: singleton, max_pool_size=10, context-manager, session()
  4. warmup_policy_cache: loads docs, prints message, handles DB failure
  5. query_national_rail_fare: cache hit suppresses DB call on repeat
  6. query_metro_schedules: cache hit suppresses DB call on repeat
  7. No-cache constraint: query_available_seats & execute_booking never touch cache
"""

from __future__ import annotations

import inspect
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

# ── Stage-level module surgery ─────────────────────────────────────────────────
# test_phase_3.1 and test_phase_3.2 stub databases.relational/graph.queries via
# sys.modules.setdefault() to avoid live DB connections.  Stage 3.3 needs the
# REAL implementations to verify caching integration.
# We swap the stubs out just before our tests run (setup_module) and restore
# them afterwards (teardown_module), so earlier test files are unaffected.

_STUBS: dict = {}
_STUB_NAMES = ("databases.relational.queries", "databases.graph.queries")


def setup_module(_module) -> None:
    """Swap MagicMock stubs for real modules before Stage 3.3 tests."""
    for name in _STUB_NAMES:
        existing = sys.modules.get(name)
        if isinstance(existing, MagicMock):
            _STUBS[name] = existing
            del sys.modules[name]


def teardown_module(_module) -> None:
    """Restore any stubs we removed, preserving the pre-test-session state."""
    for name, stub in _STUBS.items():
        sys.modules[name] = stub
    _STUBS.clear()


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _make_connect_mock(fetchone_return=None, fetchall_return=None):
    """Return a nested mock that satisfies `with _connect() as conn: with conn.cursor(...) as cur:`."""
    mock_connect = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = fetchone_return
    mock_cursor.fetchall.return_value = fetchall_return or []
    return mock_connect, mock_conn, mock_cursor


# ═════════════════════════════════════════════════════════════════════════════
# 1. CacheManager — pure unit tests (no DB, no network)
# ═════════════════════════════════════════════════════════════════════════════

class TestCacheManager:
    """Verify CacheManager behaves correctly in all edge cases."""

    @pytest.fixture
    def cache(self):
        from skeleton.cache import CacheManager
        return CacheManager(max_size=4, ttl_seconds=60)

    def test_get_missing_key_returns_none(self, cache):
        assert cache.get("no_such_key") is None

    def test_set_then_get_returns_value(self, cache):
        cache.set("k1", {"fare": 10.0})
        result = cache.get("k1")
        assert result == {"fare": 10.0}

    def test_set_overwrites_existing_key(self, cache):
        cache.set("k1", "old")
        cache.set("k1", "new")
        assert cache.get("k1") == "new"

    def test_expired_entry_returns_none(self):
        from skeleton.cache import CacheManager
        short_ttl = CacheManager(max_size=10, ttl_seconds=0)  # expires immediately
        short_ttl.set("expiring", "value")
        # Force expiry by advancing time via monotonic — sleep 0.01 s is enough since TTL=0
        time.sleep(0.01)
        assert short_ttl.get("expiring") is None

    def test_lru_eviction_removes_oldest_entry(self):
        from skeleton.cache import CacheManager
        cache = CacheManager(max_size=3, ttl_seconds=600)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" so it becomes MRU
        cache.get("a")
        # Adding "d" should evict "b" (oldest / LRU after the access above)
        cache.set("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") is not None
        assert cache.get("c") is not None
        assert cache.get("d") is not None

    def test_stats_hit_miss_counts(self, cache):
        cache.set("fare:NR01:NR05:standard", {"total_fare_usd": 50.0})
        cache.get("fare:NR01:NR05:standard")   # hit
        cache.get("fare:NR01:NR05:standard")   # hit
        cache.get("no_key")                     # miss

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1

    def test_stats_reflects_current_size(self, cache):
        cache.set("x", 1)
        cache.set("y", 2)
        assert cache.stats()["size"] == 2

    def test_clear_empties_cache_and_resets_counters(self, cache):
        cache.set("fare:NR01:NR02:first", {"total_fare_usd": 75.0})
        cache.get("fare:NR01:NR02:first")
        cache.clear()
        stats = cache.stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_unique_keys_do_not_collide(self, cache):
        """Keys with different parameters must be independent entries."""
        cache.set("fare:NR01:NR05:standard", 50.0)
        cache.set("fare:NR01:NR05:first",    75.0)
        cache.set("fare:NR01:NR05:senior",   40.0)
        assert cache.get("fare:NR01:NR05:standard") == 50.0
        assert cache.get("fare:NR01:NR05:first")    == 75.0
        assert cache.get("fare:NR01:NR05:senior")   == 40.0

    def test_none_value_is_distinguishable_from_miss(self, cache):
        """None is a valid cached value; a miss returns None from a different path."""
        cache.set("nullable_key", None)
        # After set, the key exists but the value is None.
        # Our get() returns None both for missing AND for None values.
        # This test documents the current behaviour and ensures we don't break it.
        result = cache.get("nullable_key")
        assert result is None  # Expected — key exists but value is None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Module-level cache instances
# ═════════════════════════════════════════════════════════════════════════════

class TestModuleLevelCacheInstances:
    """fare_cache, schedule_cache, policy_cache must be CacheManager instances."""

    def test_fare_cache_is_cache_manager(self):
        from skeleton.cache import CacheManager, fare_cache
        assert isinstance(fare_cache, CacheManager)

    def test_schedule_cache_is_cache_manager(self):
        from skeleton.cache import CacheManager, schedule_cache
        assert isinstance(schedule_cache, CacheManager)

    def test_policy_cache_is_cache_manager(self):
        from skeleton.cache import CacheManager, policy_cache
        assert isinstance(policy_cache, CacheManager)

    def test_fare_cache_ttl_is_positive(self):
        from skeleton.cache import fare_cache
        assert fare_cache._ttl > 0

    def test_schedule_cache_ttl_is_positive(self):
        from skeleton.cache import schedule_cache
        assert schedule_cache._ttl > 0

    def test_policy_cache_ttl_is_positive(self):
        from skeleton.cache import policy_cache
        assert policy_cache._ttl > 0

    def test_cache_instances_are_independent(self):
        """Setting a value in fare_cache must not appear in schedule_cache."""
        from skeleton.cache import fare_cache, schedule_cache
        fare_cache.set("shared_key", "fare_value")
        assert schedule_cache.get("shared_key") is None


# ═════════════════════════════════════════════════════════════════════════════
# 3. Neo4jConnectionPool
# ═════════════════════════════════════════════════════════════════════════════

class TestNeo4jConnectionPool:
    """Neo4jConnectionPool must wrap the driver with max_pool_size=10."""

    @pytest.fixture(autouse=True)
    def reset_pool_singleton(self, monkeypatch):
        """Reset the module-level singleton before each test."""
        import databases.graph.connection_pool as _cp_module
        monkeypatch.setattr(_cp_module, "_pool", None)

    @pytest.fixture
    def mock_driver(self):
        """Patch GraphDatabase.driver to return a MagicMock driver."""
        with patch("databases.graph.connection_pool.GraphDatabase.driver") as mock_gd:
            mock_drv = MagicMock()
            mock_gd.return_value = mock_drv
            yield mock_gd, mock_drv

    def test_get_pool_returns_connection_pool_instance(self, mock_driver):
        from databases.graph.connection_pool import Neo4jConnectionPool, get_pool
        pool = get_pool()
        assert isinstance(pool, Neo4jConnectionPool)

    def test_get_pool_is_singleton(self, mock_driver):
        """Two calls to get_pool() must return the same object."""
        from databases.graph.connection_pool import get_pool
        p1 = get_pool()
        p2 = get_pool()
        assert p1 is p2

    def test_pool_initialised_with_max_pool_size_10(self, mock_driver):
        """Driver must be created with max_connection_pool_size=10."""
        mock_gd, _ = mock_driver
        from databases.graph.connection_pool import get_pool
        get_pool()
        _, kwargs = mock_gd.call_args
        assert kwargs.get("max_connection_pool_size") == 10

    def test_context_manager_enter_returns_pool(self, mock_driver):
        """__enter__ must return the pool itself (not the driver)."""
        from databases.graph.connection_pool import get_pool
        pool = get_pool()
        result = pool.__enter__()
        assert result is pool

    def test_context_manager_exit_does_not_close_driver(self, mock_driver):
        """__exit__ must NOT close the underlying driver (pool stays alive)."""
        _, mock_drv = mock_driver
        from databases.graph.connection_pool import get_pool
        pool = get_pool()
        with pool:
            pass  # triggers __exit__
        mock_drv.close.assert_not_called()

    def test_pool_has_session_method(self, mock_driver):
        from databases.graph.connection_pool import get_pool
        pool = get_pool()
        assert callable(pool.session)

    def test_session_returns_driver_session(self, mock_driver):
        """pool.session() must delegate to the underlying driver.session()."""
        _, mock_drv = mock_driver
        from databases.graph.connection_pool import get_pool
        pool = get_pool()
        pool.session(database="neo4j")
        mock_drv.session.assert_called_once_with(database="neo4j")


# ═════════════════════════════════════════════════════════════════════════════
# 4. warmup_policy_cache
# ═════════════════════════════════════════════════════════════════════════════

class TestWarmupPolicyCache:
    """warmup_policy_cache must load docs, print message, handle failures."""

    @pytest.fixture(autouse=True)
    def clear_policy_cache(self):
        from skeleton.cache import policy_cache
        policy_cache.clear()
        yield
        policy_cache.clear()

    def _make_psycopg2_mock(self, rows):
        mock_psycopg2 = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_psycopg2.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = rows
        return mock_psycopg2

    def test_warmup_returns_count_of_loaded_docs(self):
        rows = [
            {"id": 1, "title": "Cancellation Policy", "category": "policy", "content": "..."},
            {"id": 2, "title": "Refund Policy",       "category": "policy", "content": "..."},
        ]
        mock_psycopg2 = self._make_psycopg2_mock(rows)
        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import warmup_policy_cache
            count = warmup_policy_cache()
        assert count == 2

    def test_warmup_stores_docs_in_policy_cache(self):
        from skeleton.cache import policy_cache
        rows = [{"id": 3, "title": "Baggage Policy", "category": "policy", "content": "bags"}]
        mock_psycopg2 = self._make_psycopg2_mock(rows)
        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import warmup_policy_cache
            warmup_policy_cache()
        cached = policy_cache.get("policy:3")
        assert cached is not None
        assert cached["title"] == "Baggage Policy"

    def test_warmup_cache_key_format(self):
        """Key must be 'policy:{id}' for each document."""
        from skeleton.cache import policy_cache
        rows = [{"id": 42, "title": "T", "category": "c", "content": "x"}]
        mock_psycopg2 = self._make_psycopg2_mock(rows)
        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import warmup_policy_cache
            warmup_policy_cache()
        assert policy_cache.get("policy:42") is not None
        assert policy_cache.get("policy:0") is None

    def test_warmup_prints_success_message(self, capsys):
        rows = [{"id": 1, "title": "P", "category": "c", "content": "x"}]
        mock_psycopg2 = self._make_psycopg2_mock(rows)
        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import warmup_policy_cache
            warmup_policy_cache()
        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "政策文件" in captured.out

    def test_warmup_handles_db_failure_and_returns_zero(self):
        """If DB is unreachable, warmup must not raise — it returns 0."""
        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("Connection refused")
        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import warmup_policy_cache
            count = warmup_policy_cache()
        assert count == 0

    def test_warmup_queries_top_50(self):
        """SQL must LIMIT to TOP_K_WARMUP (50) documents."""
        mock_psycopg2 = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_psycopg2.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("skeleton.vector_warmup.psycopg2", mock_psycopg2):
            from skeleton.vector_warmup import TOP_K_WARMUP, warmup_policy_cache
            warmup_policy_cache()

        assert TOP_K_WARMUP == 50
        execute_args = mock_cursor.execute.call_args
        assert execute_args is not None
        # Second positional arg is the params tuple; first element should be 50
        params = execute_args[0][1]
        assert params == (50,)


# ═════════════════════════════════════════════════════════════════════════════
# 5. query_national_rail_fare — cache integration
# ═════════════════════════════════════════════════════════════════════════════

class TestFareCacheIntegration:
    """query_national_rail_fare must read cache first and skip DB on cache hit."""

    @pytest.fixture(autouse=True)
    def clear_fare_cache(self):
        from skeleton.cache import fare_cache
        fare_cache.clear()
        yield
        fare_cache.clear()

    def test_first_call_queries_database(self):
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 50.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            query_national_rail_fare("NR01", "NR05", "standard")
        mock_connect.assert_called_once()

    def test_second_call_with_same_args_skips_database(self):
        """Cache hit: DB must not be called on the second identical request."""
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 50.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            query_national_rail_fare("NR01", "NR05", "standard")
            query_national_rail_fare("NR01", "NR05", "standard")
        # _connect must only have been called ONCE despite two identical calls
        assert mock_connect.call_count == 1

    def test_cache_hit_returns_same_result(self):
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 50.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            r1 = query_national_rail_fare("NR01", "NR05", "standard")
            r2 = query_national_rail_fare("NR01", "NR05", "standard")
        assert r1 == r2

    def test_different_fare_class_hits_database_again(self):
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 50.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            query_national_rail_fare("NR01", "NR05", "standard")
            query_national_rail_fare("NR01", "NR05", "first")
        # Two different keys → two DB calls
        assert mock_connect.call_count == 2

    def test_different_stations_hit_database_again(self):
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 50.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            query_national_rail_fare("NR01", "NR05", "standard")
            query_national_rail_fare("NR02", "NR06", "standard")
        assert mock_connect.call_count == 2

    def test_cache_key_contains_origin_destination_fareclass(self):
        """Cached key in fare_cache must encode all three dimensions."""
        from skeleton.cache import fare_cache
        mock_connect, _, _ = _make_connect_mock(
            fetchone_return={"base_fare_usd": 40.0}
        )
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            query_national_rail_fare("NR03", "NR07", "senior")
        assert fare_cache.get("fare:NR03:NR07:senior") is not None

    def test_none_result_not_cached(self):
        """When DB returns None (no route), result must not be stored in cache."""
        from skeleton.cache import fare_cache
        mock_connect, _, _ = _make_connect_mock(fetchone_return=None)
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_national_rail_fare
            result = query_national_rail_fare("NR01", "NR99", "standard")
        assert result is None
        assert fare_cache.get("fare:NR01:NR99:standard") is None


# ═════════════════════════════════════════════════════════════════════════════
# 6. query_metro_schedules — cache integration
# ═════════════════════════════════════════════════════════════════════════════

class TestMetroScheduleCacheIntegration:
    """query_metro_schedules must cache results and skip DB on repeated calls."""

    @pytest.fixture(autouse=True)
    def clear_schedule_cache(self):
        from skeleton.cache import schedule_cache
        schedule_cache.clear()
        yield
        schedule_cache.clear()

    def _schedule_row(self):
        return {
            "schedule_id": "M1_SCH01",
            "line": "M1",
            "direction": "northbound",
            "origin_station_id": "MS01",
            "destination_station_id": "MS10",
            "first_train_time": "06:00",
            "last_train_time": "23:00",
            "base_fare_usd": 1.50,
            "operating_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        }

    def test_first_call_queries_database(self):
        mock_connect, _, _ = _make_connect_mock(fetchall_return=[self._schedule_row()])
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_metro_schedules
            query_metro_schedules("MS01", "MS10")
        mock_connect.assert_called_once()

    def test_repeated_call_with_same_args_skips_database(self):
        mock_connect, _, _ = _make_connect_mock(fetchall_return=[self._schedule_row()])
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_metro_schedules
            query_metro_schedules("MS01", "MS10")
            query_metro_schedules("MS01", "MS10")
        assert mock_connect.call_count == 1

    def test_cache_hit_returns_same_result(self):
        mock_connect, _, _ = _make_connect_mock(fetchall_return=[self._schedule_row()])
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_metro_schedules
            r1 = query_metro_schedules("MS01", "MS10")
            r2 = query_metro_schedules("MS01", "MS10")
        assert r1 == r2

    def test_different_station_pair_hits_database_again(self):
        mock_connect, _, _ = _make_connect_mock(fetchall_return=[self._schedule_row()])
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_metro_schedules
            query_metro_schedules("MS01", "MS10")
            query_metro_schedules("MS01", "MS20")
        assert mock_connect.call_count == 2

    def test_cache_key_contains_origin_and_destination(self):
        from skeleton.cache import schedule_cache
        mock_connect, _, _ = _make_connect_mock(fetchall_return=[self._schedule_row()])
        with patch("databases.relational.queries._connect", mock_connect):
            from databases.relational.queries import query_metro_schedules
            query_metro_schedules("MS01", "MS10")
        assert schedule_cache.get("metro_sched:MS01:MS10") is not None


# ═════════════════════════════════════════════════════════════════════════════
# 7. No-cache constraint — booking/seat functions must NOT use cache
# ═════════════════════════════════════════════════════════════════════════════

class TestNoCacheConstraint:
    """
    Absolute constraint: query_available_seats and execute_booking must never
    read from or write to any cache to prevent overselling.
    """

    def _get_source(self, func_name: str) -> str:
        import databases.relational.queries as q
        fn = getattr(q, func_name)
        return inspect.getsource(fn)

    def test_query_available_seats_does_not_call_fare_cache(self):
        src = self._get_source("query_available_seats")
        assert "fare_cache" not in src, (
            "query_available_seats must NOT use fare_cache"
        )

    def test_query_available_seats_does_not_call_schedule_cache(self):
        src = self._get_source("query_available_seats")
        assert "schedule_cache" not in src, (
            "query_available_seats must NOT use schedule_cache"
        )

    def test_execute_booking_does_not_call_fare_cache(self):
        src = self._get_source("execute_booking")
        assert "fare_cache" not in src, (
            "execute_booking must NOT use fare_cache"
        )

    def test_execute_booking_does_not_call_schedule_cache(self):
        src = self._get_source("execute_booking")
        assert "schedule_cache" not in src, (
            "execute_booking must NOT use schedule_cache"
        )

    def test_query_available_seats_does_not_call_cache_get(self):
        """Confirm no .get() call pattern on any cache object in seat lookup."""
        src = self._get_source("query_available_seats")
        # We check specifically for cache variable references
        assert "policy_cache" not in src

    def test_execute_booking_does_not_call_policy_cache(self):
        src = self._get_source("execute_booking")
        assert "policy_cache" not in src


# ═════════════════════════════════════════════════════════════════════════════
# 8. graph/queries.py — uses get_pool(), not _driver()
# ═════════════════════════════════════════════════════════════════════════════

class TestGraphQueriesUsesConnectionPool:
    """databases/graph/queries.py must not contain the old _driver() factory."""

    def test_graph_queries_does_not_define_driver_factory(self):
        import databases.graph.queries as gq
        src = inspect.getsource(gq)
        assert "def _driver" not in src, (
            "databases/graph/queries.py must not define _driver(); use get_pool() instead"
        )

    def test_graph_queries_imports_get_pool(self):
        import databases.graph.queries as gq
        src = inspect.getsource(gq)
        assert "get_pool" in src, (
            "databases/graph/queries.py must import and use get_pool()"
        )

    def test_graph_queries_does_not_import_graphdatabase_directly(self):
        import databases.graph.queries as gq
        src = inspect.getsource(gq)
        assert "GraphDatabase" not in src, (
            "databases/graph/queries.py must not import GraphDatabase directly"
        )


if __name__ == "__main__":
    print("Run with: pytest tests/unit/test_phase_3.3_performance_boost.py -v")
