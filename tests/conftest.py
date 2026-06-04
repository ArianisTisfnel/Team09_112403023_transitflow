"""
Shared pytest fixtures for the TransitFlow test suite.
"""

import pytest


@pytest.fixture(autouse=True)
def clear_query_caches():
    """
    Reset module-level LRU caches before and after every test.

    Without this, a cached fare/schedule result from one test leaks into
    later tests that mock _connect with different return values, causing
    unexpected cache hits instead of DB calls.
    """
    from skeleton.cache import fare_cache, policy_cache, schedule_cache
    fare_cache.clear()
    schedule_cache.clear()
    policy_cache.clear()
    yield
    fare_cache.clear()
    schedule_cache.clear()
    policy_cache.clear()
