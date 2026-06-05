"""
Shared pytest fixtures for the TransitFlow test suite.
"""

import pytest

# Pre-load the real query modules so the Stage 3 tests' module-level
# `sys.modules.setdefault("databases.*.queries", MagicMock())` stubs (used to
# avoid importing a live DB/Ollama during those tests) become no-ops. Without
# this, whichever test imports first can leave a MagicMock in sys.modules that
# leaks into the relational/graph unit tests which import the real functions.
# These modules do not open any DB connection at import time, so this is safe.
import databases.relational.queries  # noqa: F401,E402
import databases.graph.queries  # noqa: F401,E402

# Out-of-scope tests kept in the repo but dormant for the current stage. They
# depend on components not yet present (Stage 3 modules: exceptions / cache /
# database_service / metrics; or the maintenance_check module). They are skipped
# at collection so the in-scope Stage 1/2 suite runs clean. Re-enable by removing
# the matching entry once the corresponding module is in place.
collect_ignore = [
    "unit/test_maintenance_check.py",          # needs skeleton.maintenance_check (not yet ported)
    "unit/test_query_round_trip_itinerary.py", # round-trip + Stage 3 exception behaviour (revisit)
    "integration/test_e2e_stage1_to_stage3.py",# end-to-end across all of Stage 3
    "unit/test_phase_3.4_ui_observability.py", # needs health_check / ui generator (Stage 3.4)
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
