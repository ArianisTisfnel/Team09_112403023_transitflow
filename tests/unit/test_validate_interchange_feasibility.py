"""
Unit tests for validate_interchange_feasibility()
Covers: DoD scenarios (5-min transfer → False, 20-min transfer → True),
        cross-midnight timestamps, empty paths, multiple interchange points.
"""

from databases.graph.queries import validate_interchange_feasibility


# ── helpers ───────────────────────────────────────────────────────────────────

def _path_with_interchange_legs(*travel_times_min):
    """Build a path_details dict using the Layout A (legs) format."""
    legs = []
    for i, t in enumerate(travel_times_min):
        legs.append({
            "from_station_id": f"MS0{i}",
            "to_station_id": f"MS0{i+1}",
            "relationship_type": "INTERCHANGE_TO",
            "travel_time_min": t,
        })
    return {"legs": legs, "interchange_points": []}


def _path_with_timestamp_points(*time_pairs):
    """Build a path_details dict using the Layout B (interchange_points) format.

    Each element of time_pairs is (arrival_str, departure_str).
    """
    points = [
        {"arrival_time": arr, "departure_time": dep}
        for arr, dep in time_pairs
    ]
    return {"legs": [], "interchange_points": points}


# ── DoD: core acceptance scenarios ───────────────────────────────────────────

def test_5_minute_interchange_returns_false():
    """DoD: a 5-minute transfer at an interchange must return False."""
    path = _path_with_interchange_legs(5)
    assert validate_interchange_feasibility(path) is False
    print("✓ 5-minute interchange → False")


def test_15_minute_interchange_returns_true():
    """Exactly 15 minutes is the minimum — must return True."""
    path = _path_with_interchange_legs(15)
    assert validate_interchange_feasibility(path) is True
    print("✓ 15-minute interchange → True")


def test_20_minute_interchange_returns_true():
    """A comfortable 20-minute transfer must return True."""
    path = _path_with_interchange_legs(20)
    assert validate_interchange_feasibility(path) is True
    print("✓ 20-minute interchange → True")


# ── multiple interchange points ───────────────────────────────────────────────

def test_all_interchanges_sufficient_returns_true():
    """All interchange legs >= 15 min → True."""
    path = {
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 10},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 20},
            {"relationship_type": "METRO_LINK",  "travel_time_min": 8},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 15},
        ],
        "interchange_points": [],
    }
    assert validate_interchange_feasibility(path) is True
    print("✓ multiple sufficient interchanges → True")


def test_one_insufficient_interchange_returns_false():
    """One interchange leg below 15 min makes the whole path infeasible."""
    path = {
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 5},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 20},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 10},  # ← too short
        ],
        "interchange_points": [],
    }
    assert validate_interchange_feasibility(path) is False
    print("✓ one insufficient interchange among many → False")


# ── Layout A: non-INTERCHANGE legs are ignored ───────────────────────────────

def test_connects_to_legs_are_ignored():
    """CONNECTS_TO legs with any travel_time_min must not affect the result."""
    path = {
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 2},
            {"relationship_type": "METRO_LINK", "travel_time_min": 3},
        ],
        "interchange_points": [],
    }
    assert validate_interchange_feasibility(path) is True
    print("✓ CONNECTS_TO legs ignored — no interchange → True")


# ── empty / no-interchange paths ─────────────────────────────────────────────

def test_empty_path_returns_true():
    """An empty dict (no legs, no points) has nothing to fail → True."""
    assert validate_interchange_feasibility({}) is True
    print("✓ empty path_details → True")


def test_path_without_interchange_legs_returns_true():
    """Path with legs but no INTERCHANGE relationships is vacuously valid."""
    path = {
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 5},
            {"relationship_type": "METRO_LINK", "travel_time_min": 8},
        ],
        "interchange_points": [],
    }
    assert validate_interchange_feasibility(path) is True
    print("✓ path with no INTERCHANGE legs → True")


# ── Layout B: explicit timestamp-based interchange points ────────────────────

def test_timestamp_14_minute_gap_returns_false():
    """Layout B: arrival 10:00, departure 10:14 → 14 min < 15 → False."""
    path = _path_with_timestamp_points(("10:00", "10:14"))
    assert validate_interchange_feasibility(path) is False
    print("✓ 14-minute timestamp gap → False")


def test_timestamp_15_minute_gap_returns_true():
    """Layout B: arrival 10:00, departure 10:15 → exactly 15 min → True."""
    path = _path_with_timestamp_points(("10:00", "10:15"))
    assert validate_interchange_feasibility(path) is True
    print("✓ 15-minute timestamp gap → True")


def test_cross_midnight_timestamp_returns_true():
    """Layout B: arrival 23:55, departure 00:20 → 25 min cross-midnight → True."""
    path = _path_with_timestamp_points(("23:55", "00:20"))
    assert validate_interchange_feasibility(path) is True
    print("✓ cross-midnight 25-minute gap → True")


def test_cross_midnight_timestamp_short_gap_returns_false():
    """Layout B: arrival 23:58, departure 00:05 → 7 min cross-midnight → False."""
    path = _path_with_timestamp_points(("23:58", "00:05"))
    assert validate_interchange_feasibility(path) is False
    print("✓ cross-midnight 7-minute gap → False")


# ── Layout B: transfer_time_min fallback ─────────────────────────────────────

def test_transfer_time_min_field_5_returns_false():
    """Layout B fallback: transfer_time_min=5 without timestamps → False."""
    path = {"legs": [], "interchange_points": [{"transfer_time_min": 5}]}
    assert validate_interchange_feasibility(path) is False
    print("✓ transfer_time_min=5 fallback → False")


def test_transfer_time_min_field_20_returns_true():
    """Layout B fallback: transfer_time_min=20 without timestamps → True."""
    path = {"legs": [], "interchange_points": [{"transfer_time_min": 20}]}
    assert validate_interchange_feasibility(path) is True
    print("✓ transfer_time_min=20 fallback → True")


# ── realistic query_interchange_path output ──────────────────────────────────

def test_realistic_interchange_path_output_feasible():
    """Simulate feasible output from query_interchange_path (travel_time_min=20)."""
    path_details = {
        "found": True,
        "origin_id": "MS03",
        "destination_id": "NR06",
        "station_ids": ["MS03", "MS04", "NR05", "NR06"],
        "stations": [],
        "interchange_points": [
            {
                "from_station_id": "MS04",
                "from_network": "metro",
                "to_station_id": "NR05",
                "to_network": "national_rail",
            }
        ],
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 5},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 20},
            {"relationship_type": "METRO_LINK",  "travel_time_min": 8},
        ],
        "total_travel_time_min": 33,
    }
    assert validate_interchange_feasibility(path_details) is True
    print("✓ realistic feasible interchange path → True")


def test_realistic_interchange_path_output_infeasible():
    """Simulate infeasible output from query_interchange_path (travel_time_min=5)."""
    path_details = {
        "found": True,
        "origin_id": "MS03",
        "destination_id": "NR06",
        "station_ids": ["MS03", "MS04", "NR05", "NR06"],
        "stations": [],
        "interchange_points": [],
        "legs": [
            {"relationship_type": "METRO_LINK", "travel_time_min": 5},
            {"relationship_type": "INTERCHANGE_TO",  "travel_time_min": 5},   # ← too short
            {"relationship_type": "METRO_LINK",  "travel_time_min": 8},
        ],
        "total_travel_time_min": 18,
    }
    assert validate_interchange_feasibility(path_details) is False
    print("✓ realistic infeasible interchange path → False")


if __name__ == "__main__":
    test_5_minute_interchange_returns_false()
    test_15_minute_interchange_returns_true()
    test_20_minute_interchange_returns_true()
    test_all_interchanges_sufficient_returns_true()
    test_one_insufficient_interchange_returns_false()
    test_connects_to_legs_are_ignored()
    test_empty_path_returns_true()
    test_path_without_interchange_legs_returns_true()
    test_timestamp_14_minute_gap_returns_false()
    test_timestamp_15_minute_gap_returns_true()
    test_cross_midnight_timestamp_returns_true()
    test_cross_midnight_timestamp_short_gap_returns_false()
    test_transfer_time_min_field_5_returns_false()
    test_transfer_time_min_field_20_returns_true()
    test_realistic_interchange_path_output_feasible()
    test_realistic_interchange_path_output_infeasible()
    print("\n✓ All tests passed")
