"""
Unit tests for query_national_rail_fare().

Contract (docs/08-A-query-nr-fare-metro-schedules.md):
    query_national_rail_fare(schedule_id, fare_class, stops_travelled) -> Optional[dict]

The fare is base_fare_usd * fare_multiplier; stops_travelled is echoed back but
NOT used in the calculation (national_rail_schedules only stores a whole-route
base_fare_usd). Multipliers: standard 1.0, first 1.5, senior 0.8, student 0.85,
any other value defaults to 1.0. Returns None when the schedule_id is unknown.
"""

from unittest.mock import MagicMock, patch

from databases.relational.queries import query_national_rail_fare


def _mock_connect(fetchone_value):
    """Build a patched _connect whose cursor.fetchone() returns fetchone_value."""
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = fetchone_value
    return mock_connect, mock_cursor


def test_standard_class_multiplier_1_0():
    mock_connect, _ = _mock_connect({"base_fare_usd": 50.00})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 4)
    finally:
        patch.stopall()
    assert result is not None
    assert result["fare_class"] == "standard"
    assert result["base_fare_usd"] == 50.00
    assert result["fare_multiplier"] == 1.0
    assert result["total_fare_usd"] == 50.00


def test_first_class_multiplier_1_5():
    mock_connect, _ = _mock_connect({"base_fare_usd": 50.00})
    try:
        result = query_national_rail_fare("NR_SCH01", "first", 4)
    finally:
        patch.stopall()
    assert result["fare_multiplier"] == 1.5
    assert result["total_fare_usd"] == 75.00


def test_senior_class_multiplier_0_8():
    _mock_connect({"base_fare_usd": 50.00})
    try:
        result = query_national_rail_fare("NR_SCH01", "senior", 4)
    finally:
        patch.stopall()
    assert result["fare_multiplier"] == 0.8
    assert result["total_fare_usd"] == 40.00


def test_student_class_multiplier_0_85():
    _mock_connect({"base_fare_usd": 50.00})
    try:
        result = query_national_rail_fare("NR_SCH01", "student", 4)
    finally:
        patch.stopall()
    assert result["fare_multiplier"] == 0.85
    assert result["total_fare_usd"] == 42.50


def test_invalid_fare_class_defaults_to_1_0():
    _mock_connect({"base_fare_usd": 100.00})
    try:
        result = query_national_rail_fare("NR_SCH02", "platinum", 2)
    finally:
        patch.stopall()
    assert result["fare_multiplier"] == 1.0
    assert result["total_fare_usd"] == 100.00


def test_total_fare_rounded_to_two_decimals():
    # float(33.33) * 1.5 = 49.9949... -> round(., 2) == 49.99
    _mock_connect({"base_fare_usd": 33.33})
    try:
        result = query_national_rail_fare("NR_SCH01", "first", 4)
    finally:
        patch.stopall()
    assert result["total_fare_usd"] == 49.99


def test_unknown_schedule_returns_none():
    _mock_connect(None)
    try:
        result = query_national_rail_fare("NR_SCH99", "standard", 4)
    finally:
        patch.stopall()
    assert result is None


def test_stops_travelled_is_echoed_not_used_in_math():
    _mock_connect({"base_fare_usd": 12.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 7)
    finally:
        patch.stopall()
    # stops_travelled is returned unchanged and does not affect the fare
    assert result["stops_travelled"] == 7
    assert result["total_fare_usd"] == 12.50


def test_all_required_fields_present():
    _mock_connect({"base_fare_usd": 60.00})
    try:
        result = query_national_rail_fare("NR_SCH01", "first", 3)
    finally:
        patch.stopall()
    required = {
        "schedule_id", "fare_class", "stops_travelled",
        "base_fare_usd", "fare_multiplier", "total_fare_usd", "currency",
    }
    assert required.issubset(result.keys())
    assert result["currency"] == "USD"
    assert result["schedule_id"] == "NR_SCH01"


def test_query_filters_by_schedule_id():
    _, mock_cursor = _mock_connect({"base_fare_usd": 50.00})
    try:
        query_national_rail_fare("NR_SCH01", "standard", 4)
    finally:
        patch.stopall()
    sql, params = mock_cursor.execute.call_args[0]
    assert "%s" in sql
    assert "national_rail_schedules" in sql
    assert params == ("NR_SCH01",)


def test_uses_real_dict_cursor():
    mock_connect, _ = _mock_connect({"base_fare_usd": 50.00})
    try:
        query_national_rail_fare("NR_SCH01", "standard", 4)
        mock_conn = mock_connect.return_value.__enter__.return_value
        assert "cursor_factory" in mock_conn.cursor.call_args.kwargs
    finally:
        patch.stopall()
