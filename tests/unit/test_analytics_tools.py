"""
Unit tests for Stage 2.3 analytics functions:
  - query_daily_revenue_report(date)
  - query_occupancy_forecast(schedule_id, lead_days)
  - query_user_loyalty_metrics(user_id)

DoD coverage:
  - daily_revenue total equals sum of confirmed/completed booking amounts
  - occupancy rate = (booked_seats / total_seats) * 100
  - forecast is capped at 100% occupancy
  - most_traveled_routes handles ties (returns all tied routes, ordered alphabetically)
  - user_id not found returns None (no exception)
  - badge thresholds: Bronze < 5, Silver 5-19, Gold >= 20 orders
"""

import pytest
from unittest.mock import MagicMock, patch

from databases.relational.queries import (
    query_daily_revenue_report,
    query_occupancy_forecast,
    query_user_loyalty_metrics,
)


# ── Mock wiring helper ────────────────────────────────────────────────────────

def _setup_mock(mock_connect):
    """Wire mock_connect so that `with _connect() as conn: with conn.cursor() as cur:`
    yields a controllable mock_cur. Returns mock_cur."""
    mock_cur = MagicMock()
    conn = mock_connect.return_value.__enter__.return_value
    conn.cursor.return_value.__enter__.return_value = mock_cur
    return mock_cur


# ─────────────────────────────────────────────────────────────────────────────
# query_daily_revenue_report
# ─────────────────────────────────────────────────────────────────────────────

_SCHEDULE_ROWS = [
    {
        "schedule_id": "NR_SCH01",
        "order_count": 10,
        "schedule_revenue_usd": 500.00,
        "total_seats": 100,
        "booked_seats": 10,
        "occupancy_rate": 10.00,
    },
    {
        "schedule_id": "NR_SCH02",
        "order_count": 5,
        "schedule_revenue_usd": 250.00,
        "total_seats": 80,
        "booked_seats": 5,
        "occupancy_rate": 6.25,
    },
]


def test_daily_revenue_returns_required_keys():
    """Result must contain date, total_revenue_usd, and schedule_breakdown."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = _SCHEDULE_ROWS[:]
        result = query_daily_revenue_report("2025-06-01")

    assert "date" in result
    assert "total_revenue_usd" in result
    assert "schedule_breakdown" in result
    assert result["date"] == "2025-06-01"


def test_daily_revenue_total_equals_sum_of_schedule_revenues():
    """total_revenue_usd must equal the sum of all schedule_revenue_usd values."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = _SCHEDULE_ROWS[:]
        result = query_daily_revenue_report("2025-06-01")

    assert result["total_revenue_usd"] == round(500.00 + 250.00, 2)


def test_daily_revenue_schedule_breakdown_structure():
    """Each schedule entry must have the required fields."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = _SCHEDULE_ROWS[:]
        result = query_daily_revenue_report("2025-06-01")

    assert len(result["schedule_breakdown"]) == 2
    entry = result["schedule_breakdown"][0]
    required = {"schedule_id", "order_count", "schedule_revenue_usd",
                "total_seats", "booked_seats", "occupancy_rate"}
    assert required.issubset(entry.keys())


def test_daily_revenue_occupancy_rate_formula():
    """Occupancy rate must equal (booked_seats / total_seats) * 100, rounded to 2 dp."""
    row = {
        "schedule_id": "NR_SCH01",
        "order_count": 20,
        "schedule_revenue_usd": 1000.00,
        "total_seats": 100,
        "booked_seats": 20,
        "occupancy_rate": 20.00,  # DB already computes this
    }
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = [row]
        result = query_daily_revenue_report("2025-06-01")

    entry = result["schedule_breakdown"][0]
    expected = round(entry["booked_seats"] / entry["total_seats"] * 100, 2)
    assert entry["occupancy_rate"] == expected


def test_daily_revenue_empty_date_returns_zero_and_empty_list():
    """No qualifying bookings on a date must return total=0.0 and empty breakdown."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = []
        result = query_daily_revenue_report("2099-01-01")

    assert result["total_revenue_usd"] == 0.0
    assert result["schedule_breakdown"] == []


def test_daily_revenue_sql_filters_confirmed_and_completed():
    """SQL must filter bookings by status IN ('confirmed', 'completed')."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = []
        query_daily_revenue_report("2025-06-01")

    sql = mock_cur.execute.call_args[0][0]
    assert "confirmed" in sql
    assert "completed" in sql


def test_daily_revenue_uses_single_join_query():
    """Must use a single SQL query with JOIN — no Python-loop querying."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchall.return_value = []
        query_daily_revenue_report("2025-06-01")

    assert mock_cur.execute.call_count == 1, (
        "query_daily_revenue_report must issue exactly one SQL query"
    )


# ─────────────────────────────────────────────────────────────────────────────
# query_occupancy_forecast
# ─────────────────────────────────────────────────────────────────────────────

def test_occupancy_forecast_schedule_not_found():
    """Unknown schedule_id must return error='SCHEDULE_NOT_FOUND' with empty forecast."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.return_value = None  # layout lookup finds nothing
        result = query_occupancy_forecast("NR_UNKNOWN", 5)

    assert result["error"] == "SCHEDULE_NOT_FOUND"
    assert result["forecast"] == []
    # docs/22 only mandates the error flag + empty forecast for the not-found
    # case; the implementation reports the numeric fields as their empty defaults.
    assert result["total_seats"] == 0
    assert result["avg_daily_bookings"] == 0.0


def test_occupancy_forecast_returns_exactly_lead_days_entries():
    """Forecast list length must equal lead_days."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 100},   # layout
            {"avg_daily": 2.0},     # avg_daily
        ]
        mock_cur.fetchall.return_value = []
        result = query_occupancy_forecast("NR_SCH01", 7)

    assert result["error"] is None
    assert len(result["forecast"]) == 7


def test_occupancy_forecast_predicted_occupancy_capped_at_100():
    """predicted_occupancy_rate must never exceed 100% even with high booking velocity."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 10},      # small capacity
            {"avg_daily": 200.0},     # extremely high pace
        ]
        mock_cur.fetchall.return_value = []
        result = query_occupancy_forecast("NR_SCH01", 3)

    for day in result["forecast"]:
        assert day["predicted_occupancy_rate"] <= 100.0, (
            f"Day {day['days_from_today']} exceeds 100%: {day['predicted_occupancy_rate']}"
        )


def test_occupancy_forecast_existing_bookings_included_in_prediction():
    """Pre-existing future bookings for a date must appear in that day's forecast."""
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 100},
            {"avg_daily": 0.0},   # no new booking velocity
        ]
        mock_cur.fetchall.return_value = [
            {"travel_date": tomorrow, "existing_count": 30}
        ]
        result = query_occupancy_forecast("NR_SCH01", 3)

    first_day = result["forecast"][0]
    assert first_day["existing_bookings"] == 30
    assert first_day["predicted_occupancy_rate"] == 30.0  # 30/100 * 100


def test_occupancy_forecast_entry_has_required_keys():
    """Each forecast entry must carry the documented fields."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 100},
            {"avg_daily": 3.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_occupancy_forecast("NR_SCH01", 2)

    required = {"forecast_date", "days_from_today", "existing_bookings",
                "predicted_total", "predicted_occupancy_rate"}
    for entry in result["forecast"]:
        assert required.issubset(entry.keys()), (
            f"Missing keys in forecast entry: {required - entry.keys()}"
        )


def test_occupancy_forecast_top_level_keys():
    """Result must include schedule_id, total_seats, avg_daily_bookings, forecast, error."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 80},
            {"avg_daily": 1.5},
        ]
        mock_cur.fetchall.return_value = []
        result = query_occupancy_forecast("NR_SCH01", 1)

    for key in ("schedule_id", "total_seats", "avg_daily_bookings", "forecast", "error"):
        assert key in result
    assert result["schedule_id"] == "NR_SCH01"
    assert result["total_seats"] == 80
    assert result["avg_daily_bookings"] == 1.5


def test_occupancy_forecast_days_from_today_increments_correctly():
    """days_from_today in each entry must equal 1, 2, ..., lead_days in order."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"total_seats": 100},
            {"avg_daily": 1.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_occupancy_forecast("NR_SCH01", 5)

    days = [e["days_from_today"] for e in result["forecast"]]
    assert days == list(range(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# query_user_loyalty_metrics
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_returns_none_for_unknown_user():
    """Non-existent user_id must return None — no exception raised."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.return_value = None
        result = query_user_loyalty_metrics("USR_UNKNOWN")

    assert result is None


def test_loyalty_returns_required_keys_for_existing_user():
    """Result dict must contain the five documented top-level keys."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR001"},
            {"total_orders": 3, "total_spending_usd": 120.0},
        ]
        mock_cur.fetchall.return_value = [
            {"origin_station_id": "NR01", "destination_station_id": "NR05", "trip_count": 3}
        ]
        result = query_user_loyalty_metrics("USR001")

    for key in ("user_id", "total_orders", "total_spending_usd",
                "most_traveled_routes", "badge_level"):
        assert key in result
    assert result["user_id"] == "USR001"


def test_loyalty_badge_bronze_below_5_orders():
    """Users with < 5 orders receive Bronze."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR001"},
            {"total_orders": 3, "total_spending_usd": 90.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR001")

    assert result["badge_level"] == "Bronze"


def test_loyalty_badge_silver_5_to_19_orders():
    """Users with 5–19 orders receive Silver."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR002"},
            {"total_orders": 10, "total_spending_usd": 450.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR002")

    assert result["badge_level"] == "Silver"


def test_loyalty_badge_gold_20_or_more_orders():
    """Users with >= 20 orders receive Gold."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR003"},
            {"total_orders": 25, "total_spending_usd": 1200.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR003")

    assert result["badge_level"] == "Gold"


def test_loyalty_badge_boundary_exactly_5_is_silver():
    """Exactly 5 orders must be Silver (boundary: not Bronze)."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR004"},
            {"total_orders": 5, "total_spending_usd": 250.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR004")

    assert result["badge_level"] == "Silver"


def test_loyalty_badge_boundary_exactly_20_is_gold():
    """Exactly 20 orders must be Gold (boundary: not Silver)."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR005"},
            {"total_orders": 20, "total_spending_usd": 1000.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR005")

    assert result["badge_level"] == "Gold"


def test_loyalty_zero_orders_returns_bronze():
    """User with no bookings (total_orders=0) gets Bronze and empty routes list."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR006"},
            {"total_orders": 0, "total_spending_usd": 0.0},
        ]
        mock_cur.fetchall.return_value = []
        result = query_user_loyalty_metrics("USR006")

    assert result["badge_level"] == "Bronze"
    assert result["total_orders"] == 0
    assert result["total_spending_usd"] == 0.0
    assert result["most_traveled_routes"] == []


def test_loyalty_tie_returns_all_tied_routes():
    """When two routes share the max trip count, both must appear in most_traveled_routes."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR007"},
            {"total_orders": 6, "total_spending_usd": 300.0},
        ]
        mock_cur.fetchall.return_value = [
            {"origin_station_id": "NR01", "destination_station_id": "NR05", "trip_count": 3},
            {"origin_station_id": "NR02", "destination_station_id": "NR06", "trip_count": 3},
        ]
        result = query_user_loyalty_metrics("USR007")

    routes = result["most_traveled_routes"]
    assert len(routes) == 2, "Both tied routes must be returned"
    assert all(r["trip_count"] == 3 for r in routes), "All returned routes must share max count"


def test_loyalty_tie_routes_ordered_alphabetically():
    """Tied routes must be ordered ascending by origin_station_id, then destination."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR008"},
            {"total_orders": 8, "total_spending_usd": 400.0},
        ]
        # SQL returns them pre-sorted; verify the result preserves that order
        mock_cur.fetchall.return_value = [
            {"origin_station_id": "NR01", "destination_station_id": "NR05", "trip_count": 4},
            {"origin_station_id": "NR03", "destination_station_id": "NR07", "trip_count": 4},
        ]
        result = query_user_loyalty_metrics("USR008")

    origins = [r["origin_station_id"] for r in result["most_traveled_routes"]]
    assert origins == sorted(origins)


def test_loyalty_sql_uses_max_subquery_for_tie_detection():
    """SQL for most_traveled_routes must use MAX() subquery (not LIMIT 1) to handle ties."""
    with patch("databases.relational.queries._connect") as mock_connect:
        mock_cur = _setup_mock(mock_connect)
        mock_cur.fetchone.side_effect = [
            {"user_id": "USR009"},
            {"total_orders": 2, "total_spending_usd": 80.0},
        ]
        mock_cur.fetchall.return_value = []
        query_user_loyalty_metrics("USR009")

    # The third execute() call is the route query
    calls = mock_cur.execute.call_args_list
    route_sql = calls[2][0][0]
    assert "MAX" in route_sql.upper(), "Route query must use MAX() to detect the top trip count"


if __name__ == "__main__":
    # Quick smoke-run without pytest
    test_daily_revenue_returns_required_keys()
    test_daily_revenue_total_equals_sum_of_schedule_revenues()
    test_daily_revenue_schedule_breakdown_structure()
    test_daily_revenue_occupancy_rate_formula()
    test_daily_revenue_empty_date_returns_zero_and_empty_list()
    test_daily_revenue_sql_filters_confirmed_and_completed()
    test_daily_revenue_uses_single_join_query()
    test_occupancy_forecast_schedule_not_found()
    test_occupancy_forecast_returns_exactly_lead_days_entries()
    test_occupancy_forecast_predicted_occupancy_capped_at_100()
    test_occupancy_forecast_existing_bookings_included_in_prediction()
    test_occupancy_forecast_entry_has_required_keys()
    test_occupancy_forecast_top_level_keys()
    test_occupancy_forecast_days_from_today_increments_correctly()
    test_loyalty_returns_none_for_unknown_user()
    test_loyalty_returns_required_keys_for_existing_user()
    test_loyalty_badge_bronze_below_5_orders()
    test_loyalty_badge_silver_5_to_19_orders()
    test_loyalty_badge_gold_20_or_more_orders()
    test_loyalty_badge_boundary_exactly_5_is_silver()
    test_loyalty_badge_boundary_exactly_20_is_gold()
    test_loyalty_zero_orders_returns_bronze()
    test_loyalty_tie_returns_all_tied_routes()
    test_loyalty_tie_routes_ordered_alphabetically()
    test_loyalty_sql_uses_max_subquery_for_tie_detection()
    print("\n✓ All 25 tests passed")
