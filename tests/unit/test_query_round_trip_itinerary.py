"""
Unit tests for query_round_trip_itinerary()

DoD coverage:
  - return_date earlier than outbound_date → raises ValidationException
  - 15% discount correctly applied to total price
  - Result contains schedule_id and seat info for both legs
"""

import pytest
from unittest.mock import patch

from databases.relational.queries import query_round_trip_itinerary
from skeleton.exceptions import ValidationException


# ── Shared mock data ──────────────────────────────────────────────────────────

_OUTBOUND_SCHEDULE = {
    "schedule_id": "NR_SCH01",
    "line": "West Coast",
    "direction": "southbound",
    "origin_station_id": "NR01",
    "destination_station_id": "NR05",
    "first_train_time": "06:00:00",
    "last_train_time": "22:00:00",
    "base_fare_usd": 50.00,
    "travel_date": "2025-06-05",
    "total_seats": 100,
    "booked_seats": 20,
    "available_seats": 80,
}

_RETURN_SCHEDULE = {
    "schedule_id": "NR_SCH05",
    "line": "West Coast",
    "direction": "northbound",
    "origin_station_id": "NR05",
    "destination_station_id": "NR01",
    "first_train_time": "07:00:00",
    "last_train_time": "23:00:00",
    "base_fare_usd": 50.00,
    "travel_date": "2025-06-10",
    "total_seats": 100,
    "booked_seats": 10,
    "available_seats": 90,
}

_OUTBOUND_FARE = {
    "origin_id": "NR01",
    "destination_id": "NR05",
    "fare_class": "standard",
    "base_fare_usd": 50.00,
    "fare_multiplier": 1.0,
    "total_fare_usd": 50.00,
    "currency": "USD",
}

_RETURN_FARE = {
    "origin_id": "NR05",
    "destination_id": "NR01",
    "fare_class": "standard",
    "base_fare_usd": 60.00,
    "fare_multiplier": 1.0,
    "total_fare_usd": 60.00,
    "currency": "USD",
}


def _patch_both(avail_side_effect, fare_side_effect):
    """Return a combined patch context for availability and fare lookups."""
    avail_patch = patch(
        "databases.relational.queries.query_national_rail_availability",
        side_effect=avail_side_effect,
    )
    fare_patch = patch(
        "databases.relational.queries.query_national_rail_fare",
        side_effect=fare_side_effect,
    )
    return avail_patch, fare_patch


# ── DoD 1: ValidationException when return_date before outbound_date ──────────

def test_raises_validation_exception_when_return_before_outbound():
    """return_date < outbound_date must raise ValidationException."""
    with pytest.raises(ValidationException) as exc_info:
        query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-04", "standard")

    assert exc_info.value.error_code == "INVALID_DATE_ORDER"
    assert "return_date" in str(exc_info.value).lower() or "2025-06-04" in str(exc_info.value)


def test_raises_validation_exception_for_invalid_date_format():
    """Malformed date strings must raise ValidationException."""
    with pytest.raises(ValidationException) as exc_info:
        query_round_trip_itinerary("NR01", "NR05", "not-a-date", "2025-06-10", "standard")

    assert exc_info.value.error_code == "INVALID_DATE_FORMAT"


# ── DoD 2: 15% discount correctly applied ────────────────────────────────────

def test_15_percent_discount_applied_to_total():
    """(outbound_fare + return_fare) * 0.85 == total_discounted_price."""
    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-10", "standard")

    # 50.00 + 60.00 = 110.00  →  110.00 * 0.85 = 93.50
    assert result["outbound_fare_usd"] == 50.00
    assert result["return_fare_usd"] == 60.00
    assert result["total_undiscounted_price"] == 110.00
    assert result["discount_rate"] == 0.15
    assert result["total_discounted_price"] == 93.50
    assert result["currency"] == "USD"


def test_discount_rounds_to_two_decimal_places():
    """Discount result must be rounded to 2 decimal places."""
    outbound_fare = {**_OUTBOUND_FARE, "total_fare_usd": 33.33}
    return_fare = {**_RETURN_FARE, "total_fare_usd": 33.33}

    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [outbound_fare, return_fare],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-10", "standard")

    # 33.33 + 33.33 = 66.66  →  66.66 * 0.85 = 56.661  →  rounded 56.66
    assert result["total_discounted_price"] == round(66.66 * 0.85, 2)
    assert isinstance(result["total_discounted_price"], float)


# ── DoD 3: Result contains schedule_id and seat info for both legs ────────────

def test_outbound_options_contain_schedule_id_and_seat_info():
    """outbound_options must include schedule_id and seat availability fields."""
    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-10", "standard")

    assert len(result["outbound_options"]) == 1
    outbound = result["outbound_options"][0]
    assert outbound["schedule_id"] == "NR_SCH01"
    assert "total_seats" in outbound
    assert "booked_seats" in outbound
    assert "available_seats" in outbound


def test_return_options_contain_schedule_id_and_seat_info():
    """return_options must include schedule_id and seat availability fields."""
    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-10", "standard")

    assert len(result["return_options"]) == 1
    ret = result["return_options"][0]
    assert ret["schedule_id"] == "NR_SCH05"
    assert "total_seats" in ret
    assert "booked_seats" in ret
    assert "available_seats" in ret


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_same_day_return_is_valid():
    """return_date equal to outbound_date must NOT raise (same-day return allowed)."""
    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-05", "standard")

    assert "total_discounted_price" in result


def test_result_contains_all_required_keys():
    """Return dict must include the documented top-level keys."""
    avail_patch, fare_patch = _patch_both(
        [[_OUTBOUND_SCHEDULE], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR05", "2025-06-05", "2025-06-10", "standard")

    required_keys = {
        "origin_id", "destination_id", "outbound_date", "return_date",
        "fare_class", "outbound_options", "return_options",
        "outbound_fare_usd", "return_fare_usd",
        "total_undiscounted_price", "discount_rate",
        "total_discounted_price", "currency",
    }
    assert required_keys.issubset(result.keys())
    assert result["origin_id"] == "NR01"
    assert result["destination_id"] == "NR05"


def test_no_outbound_schedules_returns_empty_list():
    """Empty availability for outbound leg must yield empty outbound_options."""
    avail_patch, fare_patch = _patch_both(
        [[], [_RETURN_SCHEDULE]],
        [_OUTBOUND_FARE, _RETURN_FARE],
    )
    with avail_patch, fare_patch:
        result = query_round_trip_itinerary("NR01", "NR99", "2025-06-05", "2025-06-10", "standard")

    assert result["outbound_options"] == []
    assert len(result["return_options"]) == 1
