"""
Unit tests for query_user_bookings().

Contract (docs/06-A-query-user-profile-bookings.md / AI_SESSION_CONTEXT.md):
    query_user_bookings(user_email) -> dict
    -> always returns {"national_rail": [...], "metro": [...]}

It resolves the user via query_user_profile(email) first; an unknown email
yields {"national_rail": [], "metro": []} with no booking queries run. Both the
national-rail and metro queries JOIN station names and order by travel_date DESC.
"""

from unittest.mock import MagicMock, patch

from databases.relational.queries import query_user_bookings


def _mock_connect(profile, nr_rows=None, metro_rows=None):
    """Patch _connect; fetchone() -> profile, fetchall() -> nr_rows then metro_rows."""
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = profile
    mock_cursor.fetchall.side_effect = [nr_rows or [], metro_rows or []]
    return mock_connect, mock_cursor


_PROFILE = {"user_id": "RU01", "full_name": "Alice Tan", "email": "alice@email.com"}

_NR_BOOKING = {
    "booking_id": "BK001", "user_id": "RU01", "schedule_id": "NR_SCH01",
    "origin_station_id": "NR01", "destination_station_id": "NR05",
    "origin_name": "Central Station", "destination_name": "Stonehaven",
    "travel_date": "2026-05-13", "departure_time": "07:00",
    "ticket_type": "single", "fare_class": "standard", "coach": "A",
    "seat_id": "A01", "amount_usd": 8.50, "status": "confirmed",
    "booked_at": "2026-05-01T10:00:00+00:00", "travelled_at": None,
}

_METRO_TRIP = {
    "trip_id": "MT009", "user_id": "RU01", "schedule_id": "M1_SCH01",
    "origin_station_id": "MS01", "destination_station_id": "MS09",
    "origin_name": "Central Square", "destination_name": "Airport",
    "travel_date": "2026-05-10", "ticket_type": "single",
    "amount_usd": 2.50, "status": "completed",
    "purchased_at": "2026-05-10T08:00:00+00:00", "travelled_at": "2026-05-10T08:30:00+00:00",
}


def test_always_returns_dict_with_both_keys():
    _mock_connect(_PROFILE, [], [])
    try:
        result = query_user_bookings("alice@email.com")
    finally:
        patch.stopall()
    assert isinstance(result, dict)
    assert set(result.keys()) == {"national_rail", "metro"}


def test_unknown_user_returns_empty_structure():
    _mock_connect(None)
    try:
        result = query_user_bookings("nobody@email.com")
    finally:
        patch.stopall()
    assert result == {"national_rail": [], "metro": []}


def test_user_with_no_bookings_returns_empty_lists():
    _mock_connect(_PROFILE, [], [])
    try:
        result = query_user_bookings("alice@email.com")
    finally:
        patch.stopall()
    assert result["national_rail"] == []
    assert result["metro"] == []


def test_returns_national_rail_and_metro_bookings():
    _mock_connect(_PROFILE, [dict(_NR_BOOKING)], [dict(_METRO_TRIP)])
    try:
        result = query_user_bookings("alice@email.com")
    finally:
        patch.stopall()
    assert len(result["national_rail"]) == 1
    assert len(result["metro"]) == 1
    assert result["national_rail"][0]["booking_id"] == "BK001"
    assert result["national_rail"][0]["origin_name"] == "Central Station"
    assert result["metro"][0]["trip_id"] == "MT009"


def test_national_rail_query_joins_names_and_orders_desc():
    _, mock_cursor = _mock_connect(_PROFILE, [dict(_NR_BOOKING)], [dict(_METRO_TRIP)])
    try:
        query_user_bookings("alice@email.com")
    finally:
        patch.stopall()
    # execute is called for the profile lookup, then the NR and metro queries.
    nr_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "national_rail_bookings" in c[0][0]
    ]
    assert nr_calls, "national_rail_bookings query was not executed"
    sql, params = nr_calls[0][0]
    assert "JOIN" in sql
    assert "origin_name" in sql and "destination_name" in sql
    assert "ORDER BY" in sql and "DESC" in sql
    assert params == ("RU01",)


def test_uses_real_dict_cursor():
    mock_connect, _ = _mock_connect(_PROFILE, [], [])
    try:
        query_user_bookings("alice@email.com")
        mock_conn = mock_connect.return_value.__enter__.return_value
        assert "cursor_factory" in mock_conn.cursor.call_args.kwargs
    finally:
        patch.stopall()
