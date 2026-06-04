"""
Unit tests for query_schedules_by_date_range()
Covers: 14-day range, range validation, DB query structure.
"""

from unittest.mock import MagicMock, patch

from databases.relational.queries import query_schedules_by_date_range


# ── tests ─────────────────────────────────────────────────────────────────────

def test_valid_range_returns_schedules():
    """A valid date range returns schedules with availability info."""
    mock_rows = [
        {
            "schedule_id": "NR_SCH01",
            "line": "NR1",
            "direction": "northbound",
            "service_type": "normal",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "first_train_time": "06:00",
            "last_train_time": "22:00",
            "base_fare_usd": 50.0,
            "travel_date": "2025-06-01",
            "total_seats": 100,
            "booked_seats": 30,
            "available_seats": 70,
        },
        {
            "schedule_id": "NR_SCH01",
            "line": "NR1",
            "direction": "northbound",
            "service_type": "normal",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "first_train_time": "06:00",
            "last_train_time": "22:00",
            "base_fare_usd": 50.0,
            "travel_date": "2025-06-02",
            "total_seats": 100,
            "booked_seats": 0,
            "available_seats": 100,
        },
    ]

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cur.fetchall.return_value = mock_rows

        result = query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-14")

    assert result["error"] is None
    assert result["origin_id"] == "NR01"
    assert result["destination_id"] == "NR05"
    assert result["start_date"] == "2025-06-01"
    assert result["end_date"] == "2025-06-14"
    assert result["total_found"] == 2
    assert len(result["schedules"]) == 2

    print("✓ valid date range returns schedules")


def test_14_day_boundary_is_accepted():
    """Exactly 14 days (start + 13 days = end) is accepted without error."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cur.fetchall.return_value = []

        result = query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-14")

    assert result["error"] is None
    assert result["total_found"] == 0

    print("✓ exactly 14-day range accepted")


def test_range_exceeding_14_days_rejected():
    """A 15-day span returns DATE_RANGE_EXCEEDS_14_DAYS without hitting the DB."""
    with patch("databases.relational.queries._connect") as mock_connect:
        result = query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-16")

    assert result["error"] == "DATE_RANGE_EXCEEDS_14_DAYS"
    assert result["schedules"] == []
    mock_connect.assert_not_called()

    print("✓ 15-day range rejected with DATE_RANGE_EXCEEDS_14_DAYS")


def test_reversed_dates_rejected():
    """end_date before start_date returns INVALID_DATE_RANGE without hitting the DB."""
    with patch("databases.relational.queries._connect") as mock_connect:
        result = query_schedules_by_date_range("NR01", "NR05", "2025-06-14", "2025-06-01")

    assert result["error"] == "INVALID_DATE_RANGE"
    assert result["schedules"] == []
    mock_connect.assert_not_called()

    print("✓ reversed dates rejected with INVALID_DATE_RANGE")


def test_invalid_date_format_rejected():
    """Malformed date strings return INVALID_DATE_FORMAT without hitting the DB."""
    with patch("databases.relational.queries._connect") as mock_connect:
        result = query_schedules_by_date_range("NR01", "NR05", "01-06-2025", "14-06-2025")

    assert result["error"] == "INVALID_DATE_FORMAT"
    assert result["schedules"] == []
    mock_connect.assert_not_called()

    print("✓ bad date format rejected with INVALID_DATE_FORMAT")


def test_same_day_range_is_accepted():
    """start_date == end_date (0-day span) is valid."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cur.fetchall.return_value = []

        result = query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-01")

    assert result["error"] is None

    print("✓ same-day range accepted")


def test_sql_uses_generate_series_and_cross_join():
    """SQL must use GENERATE_SERIES date range and CROSS JOIN for date expansion."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cur.fetchall.return_value = []

        query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-14")

    sql = mock_cur.execute.call_args[0][0]
    assert "generate_series" in sql.lower()
    assert "CROSS JOIN" in sql
    assert "bookings_count" in sql
    assert "GROUP BY" in sql

    print("✓ SQL uses generate_series + CROSS JOIN for date-range expansion")


def test_sql_params_include_both_dates_and_stations():
    """Query parameters must include start/end dates and origin/destination IDs."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cur.fetchall.return_value = []

        query_schedules_by_date_range("NR01", "NR05", "2025-06-01", "2025-06-14")

    params = mock_cur.execute.call_args[0][1]
    assert "NR01" in params
    assert "NR05" in params
    assert "2025-06-01" in params
    assert "2025-06-14" in params

    print("✓ query params include dates and station IDs")


if __name__ == "__main__":
    test_valid_range_returns_schedules()
    test_14_day_boundary_is_accepted()
    test_range_exceeding_14_days_rejected()
    test_reversed_dates_rejected()
    test_invalid_date_format_rejected()
    test_same_day_range_is_accepted()
    test_sql_uses_generate_series_and_cross_join()
    test_sql_params_include_both_dates_and_stations()
    print("\n✓ All tests passed")
