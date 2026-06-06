"""
Integration tests for query_metro_fare() against the live seeded PostgreSQL.

Contract (docs/09-A-query-metro-fare-seats.md):
    query_metro_fare(schedule_id, stops_travelled) -> Optional[dict]
    -> {schedule_id, stops_travelled, base_fare_usd, per_stop_rate_usd,
        total_fare_usd}   (None if the schedule_id does not exist)

Pricing follows the source data model in metro_schedules.json:
    total_fare_usd = base_fare_usd + per_stop_rate_usd * stops_travelled
"""

from databases.relational.queries import query_metro_fare

# A schedule_id that exists in the seeded metro_schedules table.
_SCHEDULE_ID = "MS_SCH01"


def test_metro_fare_formula_short():
    result = query_metro_fare(_SCHEDULE_ID, 2)
    assert result is not None
    assert result["schedule_id"] == _SCHEDULE_ID
    assert result["stops_travelled"] == 2
    assert result["total_fare_usd"] == round(
        result["base_fare_usd"] + result["per_stop_rate_usd"] * 2, 2
    )


def test_metro_fare_zero_stops_is_base_only():
    result = query_metro_fare(_SCHEDULE_ID, 0)
    assert result is not None
    assert result["total_fare_usd"] == round(result["base_fare_usd"], 2)


def test_metro_fare_increases_with_stops():
    short = query_metro_fare(_SCHEDULE_ID, 2)
    long = query_metro_fare(_SCHEDULE_ID, 8)
    assert short is not None and long is not None
    # per_stop_rate_usd is non-negative, so more stops never costs less.
    assert long["total_fare_usd"] >= short["total_fare_usd"]
    assert long["total_fare_usd"] == round(
        long["base_fare_usd"] + long["per_stop_rate_usd"] * 8, 2
    )


def test_metro_fare_unknown_schedule_returns_none():
    assert query_metro_fare("NO_SUCH_SCHEDULE", 3) is None


def test_metro_fare_response_format():
    result = query_metro_fare(_SCHEDULE_ID, 3)
    assert result is not None
    assert {
        "schedule_id", "stops_travelled",
        "base_fare_usd", "per_stop_rate_usd", "total_fare_usd",
    } <= set(result.keys())
    assert isinstance(result["total_fare_usd"], (int, float))
    assert isinstance(result["base_fare_usd"], (int, float))
    assert isinstance(result["per_stop_rate_usd"], (int, float))
    assert isinstance(result["stops_travelled"], int)
