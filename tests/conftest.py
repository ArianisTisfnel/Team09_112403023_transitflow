"""
Shared pytest fixtures for the TransitFlow test suite.
"""

import pytest

# Out-of-scope tests kept in the repo but dormant for the current stage. They
# depend on components not yet present (Stage 3 modules: exceptions / cache /
# database_service / metrics; or the maintenance_check module). They are skipped
# at collection so the in-scope Stage 1/2 suite runs clean. Re-enable by removing
# the matching entry once the corresponding module is in place.
collect_ignore = [
    "unit/test_maintenance_check.py",          # needs skeleton.maintenance_check
    "unit/test_query_round_trip_itinerary.py", # needs skeleton.exceptions (Stage 3)
    "integration/test_e2e_stage1_to_stage3.py",# end-to-end across Stage 3
]
collect_ignore_glob = [
    "unit/test_phase_3*.py",                   # Stage 3 unit tests
]


@pytest.fixture(autouse=True)
def clear_query_caches():
    """
    Reset module-level caches before and after every test.

    Without this, a cached fare/schedule result from one test leaks into
    later tests that mock _connect with different return values, causing
    unexpected cache hits instead of DB calls.

    The cache layer is a Stage 3 component; when it is not present (Stage 1/2
    only) this fixture is a harmless no-op so the rest of the suite still runs.
    """
    try:
        from skeleton.cache import fare_cache, policy_cache, schedule_cache
    except ImportError:
        yield
        return

    fare_cache.clear()
    schedule_cache.clear()
    policy_cache.clear()
    yield
    fare_cache.clear()
    schedule_cache.clear()
    policy_cache.clear()
