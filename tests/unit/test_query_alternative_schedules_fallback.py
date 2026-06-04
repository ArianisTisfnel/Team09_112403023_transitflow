"""
Unit tests for query_alternative_schedules_fallback()
Covers: full-booking fallback, cross-midnight scheduling, unknown schedule, no alternatives.
"""

from unittest.mock import MagicMock, patch

from databases.relational.queries import query_alternative_schedules_fallback


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_mock_conn(original_row, alternatives_rows):
    """Wire up a mock _connect() whose cursor returns two fetchone/fetchall sequences."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = original_row
    mock_cur.fetchall.return_value = alternatives_rows
    return mock_conn, mock_cur


# ── tests ─────────────────────────────────────────────────────────────────────

def test_returns_up_to_3_alternatives_within_3_hours():
    """When alternatives exist, result contains list of up to 3 schedules, error is None."""
    original_row = {
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "first_train_time": "08:00:00",
    }
    alt_rows = [
        {
            "schedule_id": "NR_SCH02",
            "line": "NR1",
            "direction": "northbound",
            "service_type": "normal",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "departure_time": "09:00",
            "base_fare_usd": 50.0,
            "travel_date": "2025-06-01",
            "total_seats": 100,
            "booked_seats": 20,
            "available_seats": 80,
            "time_diff_seconds": 3600,
        },
        {
            "schedule_id": "NR_SCH03",
            "line": "NR1",
            "direction": "northbound",
            "service_type": "express",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "departure_time": "10:00",
            "base_fare_usd": 60.0,
            "travel_date": "2025-06-01",
            "total_seats": 80,
            "booked_seats": 5,
            "available_seats": 75,
            "time_diff_seconds": 7200,
        },
    ]

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn, mock_cur = _make_mock_conn(original_row, alt_rows)
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = query_alternative_schedules_fallback("NR_SCH01", "2025-06-01")

    assert result["error"] is None
    assert result["schedule_id"] == "NR_SCH01"
    assert result["travel_date"] == "2025-06-01"
    assert result["original_departure_time"] == "08:00"
    assert result["alternatives_found"] == 2
    assert len(result["alternatives"]) == 2
    assert result["alternatives"][0]["schedule_id"] == "NR_SCH02"
    assert result["alternatives"][1]["schedule_id"] == "NR_SCH03"

    print("✓ returns up to 3 alternatives within 3 hours")


def test_returns_no_alternatives_found_error_code():
    """When no seats are available on any later schedule, error is NO_ALTERNATIVES_FOUND."""
    original_row = {
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "first_train_time": "18:00:00",
    }

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn, mock_cur = _make_mock_conn(original_row, [])
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = query_alternative_schedules_fallback("NR_SCH05", "2025-06-01")

    assert result["error"] == "NO_ALTERNATIVES_FOUND"
    assert result["alternatives_found"] == 0
    assert result["alternatives"] == []
    assert result["original_departure_time"] == "18:00"

    print("✓ NO_ALTERNATIVES_FOUND when no later seats available")


def test_returns_schedule_not_found_error_code():
    """Unknown schedule_id produces SCHEDULE_NOT_FOUND error code."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn

        mock_cur.fetchone.return_value = None  # schedule not in DB

        result = query_alternative_schedules_fallback("NR_UNKNOWN", "2025-06-01")

    assert result["error"] == "SCHEDULE_NOT_FOUND"
    assert result["alternatives_found"] == 0
    assert result["original_departure_time"] is None

    print("✓ SCHEDULE_NOT_FOUND for unknown schedule_id")


def test_sql_uses_cross_midnight_mod_arithmetic():
    """SQL query must use MOD + epoch arithmetic for cross-midnight safety."""
    original_row = {
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "first_train_time": "23:00:00",
    }

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn, mock_cur = _make_mock_conn(original_row, [])
        mock_connect.return_value.__enter__.return_value = mock_conn

        query_alternative_schedules_fallback("NR_SCH_LATE", "2025-06-01")

    # Inspect the second execute() call (the alternatives query)
    calls = mock_cur.execute.call_args_list
    assert len(calls) >= 2, "Expected at least two execute() calls"
    alternatives_sql = calls[1][0][0]

    assert "MOD" in alternatives_sql, "SQL must use MOD for cross-midnight arithmetic"
    assert "EPOCH" in alternatives_sql, "SQL must use EXTRACT(EPOCH ...) for time conversion"
    assert "86400" in alternatives_sql, "SQL must use 86400 (seconds/day) for wrap-around"
    assert "10800" in alternatives_sql, "SQL must use 10800 (3 hours in seconds) as the limit"

    print("✓ SQL uses MOD + EPOCH arithmetic for cross-midnight handling")


def test_sql_filters_same_schedule_id():
    """Alternatives query must exclude the original schedule_id from results."""
    original_row = {
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "first_train_time": "08:00:00",
    }

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn, mock_cur = _make_mock_conn(original_row, [])
        mock_connect.return_value.__enter__.return_value = mock_conn

        query_alternative_schedules_fallback("NR_SCH01", "2025-06-01")

    calls = mock_cur.execute.call_args_list
    assert len(calls) >= 2
    params = calls[1][0][1]

    # schedule_id must appear as an exclusion parameter
    assert "NR_SCH01" in params, "Original schedule_id must be in query params for exclusion"

    print("✓ SQL excludes original schedule_id from alternatives")


def test_sql_limits_to_3_results():
    """Alternatives query must have LIMIT 3."""
    original_row = {
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "first_train_time": "08:00:00",
    }

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn, mock_cur = _make_mock_conn(original_row, [])
        mock_connect.return_value.__enter__.return_value = mock_conn

        query_alternative_schedules_fallback("NR_SCH01", "2025-06-01")

    calls = mock_cur.execute.call_args_list
    assert len(calls) >= 2
    sql = calls[1][0][0]
    assert "LIMIT 3" in sql

    print("✓ SQL limits alternatives to 3 results")


if __name__ == "__main__":
    test_returns_up_to_3_alternatives_within_3_hours()
    test_returns_no_alternatives_found_error_code()
    test_returns_schedule_not_found_error_code()
    test_sql_uses_cross_midnight_mod_arithmetic()
    test_sql_filters_same_schedule_id()
    test_sql_limits_to_3_results()
    print("\n✓ All tests passed")
