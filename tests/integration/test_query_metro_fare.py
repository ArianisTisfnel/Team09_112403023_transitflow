"""
Integration tests for query_metro_fare() against the live seeded PostgreSQL.

Contract (docs/09-A-query-metro-fare-seats.md):
    query_metro_fare(schedule_id, stops_travelled) -> Optional[dict]
    -> {schedule_id, stops_travelled, fare_tier, fare_usd}  (None if the
       schedule_id does not exist)

Tiered pricing by stops travelled:
    1-2 stops -> $1.50,  3-5 stops -> $2.50,  6+ stops -> $4.00
"""

from databases.relational.queries import query_metro_fare

# A schedule_id that exists in the seeded metro_schedules table.
_SCHEDULE_ID = "MS_SCH01"


def test_metro_fare_short_tier():
    result = query_metro_fare(_SCHEDULE_ID, 2)
    assert result is not None
    assert result["schedule_id"] == _SCHEDULE_ID
    assert result["stops_travelled"] == 2
    assert result["fare_tier"] == "1-2 stops"
    assert result["fare_usd"] == 1.50


def test_metro_fare_medium_tier():
    result = query_metro_fare(_SCHEDULE_ID, 4)
    assert result is not None
    assert result["fare_tier"] == "3-5 stops"
    assert result["fare_usd"] == 2.50


def test_metro_fare_long_tier():
    result = query_metro_fare(_SCHEDULE_ID, 8)
    assert result is not None
    assert result["fare_tier"] == "6+ stops"
    assert result["fare_usd"] == 4.00


def test_metro_fare_unknown_schedule_returns_none():
    assert query_metro_fare("NO_SUCH_SCHEDULE", 3) is None


def test_metro_fare_response_format():
    result = query_metro_fare(_SCHEDULE_ID, 3)
    assert result is not None
    assert {"schedule_id", "stops_travelled", "fare_tier", "fare_usd"} <= set(result.keys())
    assert isinstance(result["fare_usd"], (int, float))
    assert isinstance(result["fare_tier"], str)
    assert isinstance(result["stops_travelled"], int)
