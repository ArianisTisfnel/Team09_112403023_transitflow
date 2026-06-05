"""
Unit tests for query_metro_schedules().

Contract (docs/08-A-query-nr-fare-metro-schedules.md):
    query_metro_schedules(origin_id, destination_id) -> list[dict]

Looks up metro schedules directly by origin/destination station id (no line,
direction or date filtering). Times are formatted to "HH:MM" strings in SQL via
TO_CHAR(col, 'HH24:MI'). Returns [] when no schedule connects the two stations.
Each row contains: schedule_id, line, direction, origin_station_id,
destination_station_id, first_train_time, last_train_time, base_fare_usd,
operating_days.
"""

from unittest.mock import MagicMock, patch

from databases.relational.queries import query_metro_schedules


def _mock_connect(fetchall_value):
    """Patch _connect so cursor.fetchall() returns fetchall_value."""
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = fetchall_value
    return mock_connect, mock_cursor


_SAMPLE_ROW = {
    "schedule_id": "M1_SCH01",
    "line": "M1",
    "direction": "northbound",
    "origin_station_id": "MS01",
    "destination_station_id": "MS10",
    "first_train_time": "06:00",
    "last_train_time": "23:30",
    "base_fare_usd": 1.50,
    "operating_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
}


def test_returns_schedules_connecting_the_two_stations():
    _mock_connect([dict(_SAMPLE_ROW)])
    try:
        result = query_metro_schedules("MS01", "MS10")
    finally:
        patch.stopall()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["schedule_id"] == "M1_SCH01"
    assert result[0]["origin_station_id"] == "MS01"
    assert result[0]["destination_station_id"] == "MS10"


def test_no_matching_schedule_returns_empty_list():
    _mock_connect([])
    try:
        result = query_metro_schedules("MS01", "MS99")
    finally:
        patch.stopall()
    assert result == []


def test_required_fields_present():
    _mock_connect([dict(_SAMPLE_ROW)])
    try:
        result = query_metro_schedules("MS01", "MS10")
    finally:
        patch.stopall()
    required = {
        "schedule_id", "line", "direction",
        "origin_station_id", "destination_station_id",
        "first_train_time", "last_train_time",
        "base_fare_usd", "operating_days",
    }
    assert required.issubset(result[0].keys())


def test_times_formatted_as_strings_via_to_char():
    # At unit level the times come from SQL; verify the query asks PostgreSQL to
    # format them to HH:MM strings rather than returning raw TIME/timedelta.
    _, mock_cursor = _mock_connect([dict(_SAMPLE_ROW)])
    try:
        result = query_metro_schedules("MS01", "MS10")
    finally:
        patch.stopall()
    sql = mock_cursor.execute.call_args[0][0]
    assert "TO_CHAR" in sql
    assert "HH24:MI" in sql
    assert isinstance(result[0]["first_train_time"], str)


def test_query_filters_by_origin_and_destination():
    _, mock_cursor = _mock_connect([])
    try:
        query_metro_schedules("MS01", "MS10")
    finally:
        patch.stopall()
    sql, params = mock_cursor.execute.call_args[0]
    assert "%s" in sql
    assert "metro_schedules" in sql
    assert params == ("MS01", "MS10")


def test_uses_real_dict_cursor():
    mock_connect, _ = _mock_connect([])
    try:
        query_metro_schedules("MS01", "MS10")
        mock_conn = mock_connect.return_value.__enter__.return_value
        assert "cursor_factory" in mock_conn.cursor.call_args.kwargs
    finally:
        patch.stopall()
