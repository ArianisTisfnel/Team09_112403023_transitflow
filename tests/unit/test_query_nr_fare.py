"""
Unit tests for query_national_rail_fare().

Contract (docs/08-A-query-nr-fare-metro-schedules.md):
    query_national_rail_fare(schedule_id, fare_class, stops_travelled) -> Optional[dict]

The fare follows the source data model in national_rail_schedules.json:
    total_fare_usd = base_fare_usd + per_stop_rate_usd * stops_travelled
where base_fare_usd / per_stop_rate_usd are the per-class rates stored in the
national_rail_fare_classes table. An unknown fare_class falls back to the
schedule's 'standard' class. Returns None when the schedule has no fare data.
"""

import pytest
from unittest.mock import MagicMock, patch

from databases.relational.queries import query_national_rail_fare
from skeleton.cache import fare_cache


@pytest.fixture(autouse=True)
def _clear_fare_cache():
    """The fare cache is a module-level singleton — clear it between tests so a
    cached result from one test never satisfies another."""
    fare_cache.clear()
    yield
    fare_cache.clear()


def _mock_connect(fetchone_value):
    """Build a patched _connect whose cursor.fetchone() returns fetchone_value."""
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = fetchone_value
    return mock_connect, mock_cursor


def test_standard_fare_base_plus_per_stop():
    _mock_connect({"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 4)
    finally:
        patch.stopall()
    assert result is not None
    assert result["fare_class"] == "standard"
    assert result["base_fare_usd"] == 2.50
    assert result["per_stop_rate_usd"] == 1.50
    assert result["total_fare_usd"] == 8.50  # 2.50 + 1.50 * 4


def test_first_class_rates_differ():
    _mock_connect({"base_fare_usd": 4.00, "per_stop_rate_usd": 2.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "first", 4)
    finally:
        patch.stopall()
    assert result["per_stop_rate_usd"] == 2.50
    assert result["total_fare_usd"] == 14.00  # 4.00 + 2.50 * 4


def test_zero_stops_is_base_only():
    _mock_connect({"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 0)
    finally:
        patch.stopall()
    assert result["total_fare_usd"] == 2.50


def test_stops_drive_the_total():
    _mock_connect({"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 7)
    finally:
        patch.stopall()
    assert result["stops_travelled"] == 7
    assert result["total_fare_usd"] == round(2.50 + 1.50 * 7, 2)


def test_total_fare_rounded_to_two_decimals():
    _mock_connect({"base_fare_usd": 10.00, "per_stop_rate_usd": 0.333})
    try:
        result = query_national_rail_fare("NR_SCH01", "standard", 3)
    finally:
        patch.stopall()
    assert result["total_fare_usd"] == round(10.00 + 0.333 * 3, 2)


def test_unknown_schedule_returns_none():
    # Both the exact-class lookup and the 'standard' fallback return None.
    _mock_connect(None)
    try:
        result = query_national_rail_fare("NR_SCH99", "standard", 4)
    finally:
        patch.stopall()
    assert result is None


def test_unknown_class_falls_back_to_standard():
    # First fetchone (exact class) → None, second (standard fallback) → a row.
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [
        None,
        {"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50},
    ]
    try:
        result = query_national_rail_fare("NR_SCH01", "platinum", 2)
    finally:
        patch.stopall()
    assert result is not None
    assert result["total_fare_usd"] == round(2.50 + 1.50 * 2, 2)


def test_all_required_fields_present():
    _mock_connect({"base_fare_usd": 4.00, "per_stop_rate_usd": 2.50})
    try:
        result = query_national_rail_fare("NR_SCH01", "first", 3)
    finally:
        patch.stopall()
    required = {
        "schedule_id", "fare_class", "stops_travelled",
        "base_fare_usd", "per_stop_rate_usd", "total_fare_usd", "currency",
    }
    assert required.issubset(result.keys())
    assert result["currency"] == "USD"
    assert result["schedule_id"] == "NR_SCH01"


def test_query_uses_fare_classes_table():
    _, mock_cursor = _mock_connect({"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50})
    try:
        query_national_rail_fare("NR_SCH01", "standard", 4)
    finally:
        patch.stopall()
    sql, params = mock_cursor.execute.call_args[0]
    assert "national_rail_fare_classes" in sql
    assert params == ("NR_SCH01", "standard")


def test_uses_real_dict_cursor():
    mock_connect, _ = _mock_connect({"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50})
    try:
        query_national_rail_fare("NR_SCH01", "standard", 4)
        mock_conn = mock_connect.return_value.__enter__.return_value
        assert "cursor_factory" in mock_conn.cursor.call_args.kwargs
    finally:
        patch.stopall()
