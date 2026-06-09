"""
Integration tests for execute_cancellation() — REAL DATABASE.

Unlike the unit tests (which mock psycopg2.connect and therefore never exercise
the schema's CHECK constraints), these tests run against the live PostgreSQL
instance. This is deliberate: a fully-mocked test previously reported success
while the real cancellation failed on chk_payment_refund_consistency (a refunded
payment was inserted without refunded_at). Critical write paths must be verified
against a real database.

Skipped automatically when PostgreSQL is not reachable, so the suite still runs
in environments without Docker.
"""

import psycopg2
import pytest

from databases.relational.queries import (
    PG_DSN,
    execute_booking,
    execute_cancellation,
    query_available_seats,
)

# A schedule that has a seat layout seeded (see national_rail_seat_layouts).
_SCHEDULE = "NR_SCH01"
_USER = "RU01"
# Far-future date → falls in the >=48h refund window (full refund), and keeps
# these test bookings clearly separate from seeded historical data.
_TRAVEL_DATE = "2030-01-15"


def _pg_available() -> bool:
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="PostgreSQL not reachable — integration tests skipped"
)


def _cleanup(booking_id: str) -> None:
    """Remove a test booking and any payments it created, so re-runs stay clean."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM payments WHERE booking_id = %s", (booking_id,))
        cur.execute("DELETE FROM national_rail_bookings WHERE booking_id = %s", (booking_id,))
    conn.close()


def test_real_db_cancellation_cancels_and_refunds():
    """Booking → cancel: status flips to cancelled, a refunded payment is written
    (with refunded_at, satisfying chk_payment_refund_consistency), and the result
    dict carries a positive refund_amount."""
    if not query_available_seats(_SCHEDULE, _TRAVEL_DATE, "standard"):
        pytest.skip("no standard seats available for the test schedule")

    ok, booking = execute_booking(
        _USER, _SCHEDULE, "NR01", "NR05", _TRAVEL_DATE, "standard", "any"
    )
    assert ok is True, f"setup booking failed: {booking}"
    booking_id = booking["booking_id"]

    try:
        ok, result = execute_cancellation(booking_id, reason="Integration test")

        # 1. Succeeds (this is what the mocked test could never prove).
        assert ok is True, f"cancellation failed against real DB: {result}"
        assert isinstance(result, dict)

        # 2. result_dict includes a refund_amount (Live B10 requirement).
        assert "refund_amount" in result
        assert result["refund_amount"] > 0, "far-future booking should be fully refundable"
        assert result["refund_percent"] == 100

        # 3. Booking is actually cancelled in the database.
        conn = psycopg2.connect(PG_DSN)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, cancelled_at FROM national_rail_bookings WHERE booking_id = %s",
                (booking_id,),
            )
            status, cancelled_at = cur.fetchone()
            assert status == "cancelled"
            assert cancelled_at is not None

            # 4. A refunded payment row exists with refunded_at set.
            cur.execute(
                "SELECT status, refunded_at FROM payments "
                "WHERE booking_id = %s AND status = 'refunded'",
                (booking_id,),
            )
            pay = cur.fetchone()
            assert pay is not None, "expected a refunded payment row"
            assert pay[1] is not None, "refunded_at must be set"
        conn.close()
    finally:
        _cleanup(booking_id)


def test_real_db_cancel_nonexistent_returns_false():
    ok, msg = execute_cancellation("BK-DOES-NOT-EXIST")
    assert ok is False
    assert isinstance(msg, str)
    assert "not found" in msg.lower()


def test_real_db_double_cancel_returns_false():
    """Cancelling an already-cancelled booking returns (False, message), not an
    exception (Live B10)."""
    if not query_available_seats(_SCHEDULE, _TRAVEL_DATE, "standard"):
        pytest.skip("no standard seats available for the test schedule")

    ok, booking = execute_booking(
        _USER, _SCHEDULE, "NR01", "NR05", _TRAVEL_DATE, "standard", "any"
    )
    assert ok is True, f"setup booking failed: {booking}"
    booking_id = booking["booking_id"]

    try:
        ok1, _ = execute_cancellation(booking_id)
        assert ok1 is True
        ok2, msg2 = execute_cancellation(booking_id)
        assert ok2 is False
        assert isinstance(msg2, str)
    finally:
        _cleanup(booking_id)
