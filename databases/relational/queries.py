"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD

_ph = PasswordHasher()


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if travel_date:
                sql = """
                    WITH bookings_count AS (
                        SELECT schedule_id,
                               %s::DATE AS travel_date,
                               COUNT(*) AS booked_seats
                        FROM national_rail_bookings
                        WHERE status IN ('confirmed', 'pending')
                          AND travel_date = %s::DATE
                        GROUP BY schedule_id
                    )
                    SELECT
                        s.schedule_id, s.line, s.direction,
                        s.origin_station_id, s.destination_station_id,
                        s.first_train_time, s.last_train_time, s.base_fare_usd,
                        %s::DATE AS travel_date,
                        sl.total_seats,
                        COALESCE(bc.booked_seats, 0) AS booked_seats,
                        sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats
                    FROM national_rail_schedules s
                    LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
                    LEFT JOIN bookings_count bc ON s.schedule_id = bc.schedule_id
                    WHERE s.origin_station_id = %s
                      AND s.destination_station_id = %s
                      AND sl.total_seats - COALESCE(bc.booked_seats, 0) > 0
                    ORDER BY s.schedule_id ASC
                """
                cur.execute(sql, (travel_date, travel_date, travel_date, origin_id, destination_id))
            else:
                sql = """
                    WITH date_range AS (
                        SELECT CAST(CURRENT_DATE AS DATE) + i::INTEGER AS travel_date
                        FROM GENERATE_SERIES(0, 13) AS i
                    ),
                    bookings_count AS (
                        SELECT schedule_id, travel_date, COUNT(*) AS booked_seats
                        FROM national_rail_bookings
                        WHERE status IN ('confirmed', 'pending')
                          AND travel_date >= CURRENT_DATE
                          AND travel_date <= CURRENT_DATE + INTERVAL '13 days'
                        GROUP BY schedule_id, travel_date
                    )
                    SELECT
                        s.schedule_id, s.line, s.direction,
                        s.origin_station_id, s.destination_station_id,
                        s.first_train_time, s.last_train_time, s.base_fare_usd,
                        dr.travel_date,
                        sl.total_seats,
                        COALESCE(bc.booked_seats, 0) AS booked_seats,
                        sl.total_seats - COALESCE(bc.booked_seats, 0) AS available_seats
                    FROM national_rail_schedules s
                    CROSS JOIN date_range dr
                    LEFT JOIN national_rail_seat_layouts sl ON s.schedule_id = sl.schedule_id
                    LEFT JOIN bookings_count bc
                        ON s.schedule_id = bc.schedule_id AND bc.travel_date = dr.travel_date
                    WHERE s.origin_station_id = %s
                      AND s.destination_station_id = %s
                      AND sl.total_seats - COALESCE(bc.booked_seats, 0) > 0
                    ORDER BY dr.travel_date ASC, s.schedule_id ASC
                """
                cur.execute(sql, (origin_id, destination_id))

            return [dict(row) for row in cur.fetchall()]


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """Calculate the fare for a national rail journey."""
    FARE_MULTIPLIERS = {"standard": 1.0, "first": 1.5, "senior": 0.8, "student": 0.85}
    fare_multiplier = FARE_MULTIPLIERS.get(fare_class, 1.0)

    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT base_fare_usd FROM national_rail_schedules WHERE schedule_id = %s",
                (schedule_id,)
            )
            row = cur.fetchone()
            if row is None:
                return None

            base_fare_usd = float(row["base_fare_usd"])
            total_fare_usd = round(base_fare_usd * fare_multiplier, 2)

            return {
                "schedule_id": schedule_id,
                "fare_class": fare_class,
                "stops_travelled": stops_travelled,
                "base_fare_usd": base_fare_usd,
                "fare_multiplier": fare_multiplier,
                "total_fare_usd": total_fare_usd,
                "currency": "USD",
            }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """Return metro schedules that serve both origin and destination in the correct order."""
    sql = """
        SELECT
            schedule_id, line, direction,
            origin_station_id, destination_station_id,
            TO_CHAR(first_train_time, 'HH24:MI') AS first_train_time,
            TO_CHAR(last_train_time, 'HH24:MI') AS last_train_time,
            base_fare_usd, operating_days
        FROM metro_schedules
        WHERE origin_station_id = %s AND destination_station_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """Calculate the metro fare for a single-ticket journey."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT schedule_id FROM metro_schedules WHERE schedule_id = %s",
                (schedule_id,)
            )
            if cur.fetchone() is None:
                return None

    if stops_travelled <= 2:
        fare_tier = "1-2 stops"
        fare_usd = 1.50
    elif stops_travelled <= 5:
        fare_tier = "3-5 stops"
        fare_usd = 2.50
    else:
        fare_tier = "6+ stops"
        fare_usd = 4.00

    return {
        "schedule_id": schedule_id,
        "stops_travelled": stops_travelled,
        "fare_tier": fare_tier,
        "fare_usd": fare_usd,
    }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """Return available seats for a national rail journey on a given date."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT layout_id, schedule_id, coaches, total_seats "
                "FROM national_rail_seat_layouts WHERE schedule_id = %s",
                (schedule_id,)
            )
            layout_row = cur.fetchone()
            if layout_row is None:
                return []

            coaches_data = layout_row["coaches"]
            all_seats = []

            for coach in coaches_data:
                coach_id = coach["coach"]
                coach_fare_class = coach["fare_class"]
                if coach_fare_class == fare_class:
                    for seat in coach.get("seats", []):
                        all_seats.append({
                            "seat_id": seat["seat_id"],
                            "coach": coach_id,
                            "row": seat["row"],
                            "column": seat["column"],
                            "is_available": True,
                        })

            if not all_seats:
                return []

            cur.execute(
                """
                SELECT seat_id FROM national_rail_bookings
                WHERE schedule_id = %s
                  AND travel_date = %s::DATE
                  AND status IN ('confirmed', 'pending')
                  AND seat_id IS NOT NULL
                """,
                (schedule_id, travel_date)
            )
            booked_seat_ids = {row["seat_id"] for row in cur.fetchall()}

    for seat in all_seats:
        if seat["seat_id"] in booked_seat_ids:
            seat["is_available"] = False

    all_seats.sort(key=lambda s: (s["coach"], s["row"], s["column"]))
    return all_seats


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """Select `count` seats that are as close together as possible."""
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT user_id, full_name, email, phone,
               date_of_birth, registered_at, is_active
        FROM users
        WHERE email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            return dict(row) if row else None


def query_user_bookings(user_email: str) -> dict:
    """Return a user's combined booking history (national rail + metro)."""
    user = query_user_profile(user_email)
    if not user:
        return {"national_rail": [], "metro": []}
    user_id = user["user_id"]

    nr_sql = """
        SELECT
            b.booking_id, b.user_id, b.schedule_id,
            b.origin_station_id, b.destination_station_id,
            o.name AS origin_name,
            d.name AS destination_name,
            b.travel_date, b.departure_time, b.ticket_type,
            b.fare_class, b.coach, b.seat_id,
            b.amount_usd, b.status, b.booked_at, b.travelled_at
        FROM national_rail_bookings b
        JOIN national_rail_stations o
            ON b.origin_station_id = o.national_rail_station_id
        JOIN national_rail_stations d
            ON b.destination_station_id = d.national_rail_station_id
        WHERE b.user_id = %s
        ORDER BY b.travel_date DESC, b.departure_time DESC
    """

    metro_sql = """
        SELECT
            t.trip_id, t.user_id, t.schedule_id,
            t.origin_station_id, t.destination_station_id,
            o.name AS origin_name,
            d.name AS destination_name,
            t.travel_date, t.ticket_type,
            t.amount_usd, t.status, t.purchased_at, t.travelled_at
        FROM metro_travel_history t
        JOIN metro_stations o
            ON t.origin_station_id = o.metro_station_id
        JOIN metro_stations d
            ON t.destination_station_id = d.metro_station_id
        WHERE t.user_id = %s
        ORDER BY t.travel_date DESC
    """

    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(nr_sql, (user_id,))
            national_rail = [dict(row) for row in cur.fetchall()]
            cur.execute(metro_sql, (user_id,))
            metro = [dict(row) for row in cur.fetchall()]

    return {"national_rail": national_rail, "metro": metro}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT payment_id, booking_id, amount_usd, method, status, paid_at, refunded_at
        FROM payments
        WHERE booking_id = %s
        ORDER BY paid_at DESC
        LIMIT 1
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
            row = cur.fetchone()
            return dict(row) if row else None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """Create a national rail booking for a logged-in user."""
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Step 1: 驗證使用者
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return (False, f"User {user_id} not found")

            # Step 2: 取得班次資訊
            cur.execute(
                "SELECT schedule_id, first_train_time, base_fare_usd "
                "FROM national_rail_schedules WHERE schedule_id = %s",
                (schedule_id,)
            )
            schedule = cur.fetchone()
            if schedule is None:
                conn.rollback()
                return (False, f"Schedule {schedule_id} not found")

            departure_time = schedule["first_train_time"]
            base_fare_usd = schedule["base_fare_usd"]

            # Step 3: 計算票價
            fare_multipliers = {"standard": 1.0, "first": 1.5, "senior": 0.8, "student": 0.85}
            fare_multiplier = fare_multipliers.get(fare_class, 1.0)
            total_fare_usd = round(float(base_fare_usd) * fare_multiplier, 2)

            # Step 4: 處理座位
            if seat_id == "any":
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    conn.rollback()
                    return (False, f"No available seats in {fare_class} class for {schedule_id} on {travel_date}")
                selected_seat = available[0]
                seat_id = selected_seat["seat_id"]
                coach = selected_seat["coach"]
            else:
                coach = seat_id[0]

            # Step 5: 座位衝突偵測
            cur.execute(
                """
                SELECT booking_id FROM national_rail_bookings
                WHERE schedule_id = %s
                  AND travel_date = %s::DATE
                  AND seat_id = %s
                  AND coach = %s
                  AND status IN ('pending', 'confirmed')
                FOR UPDATE LIMIT 1
                """,
                (schedule_id, travel_date, seat_id, coach)
            )
            if cur.fetchone() is not None:
                conn.rollback()
                return (False, f"Seat {seat_id} in coach {coach} is already booked for {schedule_id} on {travel_date}")

            # Step 6: 生成 ID
            booking_id = _gen_booking_id()
            payment_id = _gen_payment_id()

            # Step 7: 插入訂票
            cur.execute(
                """
                INSERT INTO national_rail_bookings (
                    booking_id, user_id, schedule_id, origin_station_id,
                    destination_station_id, travel_date, departure_time,
                    ticket_type, fare_class, coach, seat_id, amount_usd,
                    status, booked_at
                ) VALUES (%s, %s, %s, %s, %s, %s::DATE, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (booking_id, user_id, schedule_id, origin_station_id,
                 destination_station_id, travel_date, str(departure_time),
                 ticket_type, fare_class, coach, seat_id, total_fare_usd, "pending")
            )

            # Step 8: 插入付款
            cur.execute(
                """
                INSERT INTO payments (payment_id, booking_id, amount_usd, method, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (payment_id, booking_id, total_fare_usd, "credit_card", "paid")
            )

            # Step 9: 提交
            conn.commit()

        return (True, {
            "booking_id": booking_id,
            "payment_id": payment_id,
            "user_id": user_id,
            "schedule_id": schedule_id,
            "origin_station_id": origin_station_id,
            "destination_station_id": destination_station_id,
            "travel_date": travel_date,
            "departure_time": str(departure_time),
            "ticket_type": ticket_type,
            "fare_class": fare_class,
            "coach": coach,
            "seat_id": seat_id,
            "base_fare_usd": float(base_fare_usd),
            "fare_multiplier": fare_multiplier,
            "total_fare_usd": total_fare_usd,
            "status": "pending",
            "booked_at": datetime.now(timezone.utc).isoformat(),
        })

    except psycopg2.Error as db_error:
        if conn:
            conn.rollback()
        return (False, f"Database error: {str(db_error)}")

    except Exception as general_error:
        if conn:
            conn.rollback()
        return (False, f"Booking failed: {str(general_error)}")

    finally:
        if conn:
            conn.close()


def execute_cancellation(
    booking_id: str,
    reason: str = "Customer requested",
) -> tuple[bool, dict | str]:
    """Cancel a national rail booking."""
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Step 1: 查詢訂票
            cur.execute(
                "SELECT booking_id, user_id, status, amount_usd, booked_at "
                "FROM national_rail_bookings WHERE booking_id = %s",
                (booking_id,)
            )
            booking = cur.fetchone()
            if booking is None:
                conn.rollback()
                return (False, f"Booking {booking_id} not found")

            # Step 2: 狀態機驗證
            current_status = booking["status"]
            if current_status not in ("pending", "confirmed"):
                conn.rollback()
                return (
                    False,
                    f"Cannot cancel booking with status '{current_status}'. "
                    f"Only 'pending' or 'confirmed' bookings can be cancelled."
                )

            # Step 3: 更新訂票狀態
            cancelled_at_timestamp = datetime.now(timezone.utc)
            cur.execute(
                """
                UPDATE national_rail_bookings
                SET status = 'cancelled',
                    cancellation_reason = %s,
                    cancelled_at = %s
                WHERE booking_id = %s
                """,
                (reason, cancelled_at_timestamp, booking_id)
            )
            if cur.rowcount == 0:
                conn.rollback()
                return (False, f"Failed to update booking {booking_id}")

            # Step 4: 新增退款記錄
            payment_id = _gen_payment_id()
            cur.execute(
                """
                INSERT INTO payments (payment_id, booking_id, amount_usd, method, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (payment_id, booking_id, booking["amount_usd"], "cancellation", "refunded")
            )

            conn.commit()

        return (True, {
            "booking_id": booking_id,
            "original_amount_usd": float(booking["amount_usd"]),
            "status": "cancelled",
            "cancelled_at": cancelled_at_timestamp.isoformat(),
            "cancellation_reason": reason,
            "cancellation_timestamp_utc": cancelled_at_timestamp.isoformat(),
            "original_status": current_status,
        })

    except psycopg2.Error as db_error:
        if conn:
            conn.rollback()
        return (False, f"Database error: {str(db_error)}")

    except Exception as e:
        if conn:
            conn.rollback()
        return (False, f"Cancellation failed: {str(e)}")

    finally:
        if conn:
            conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """Register a new user."""
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 檢查 email 唯一性
            cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                conn.rollback()
                return (False, f"Email '{email}' is already registered")

            # 計算下一個 user_id 序號
            cur.execute(
                "SELECT MAX(CAST(SUBSTRING(user_id FROM 3) AS INTEGER)) AS max_seq "
                "FROM users WHERE user_id ~ '^RU[0-9]+$'"
            )
            row = cur.fetchone()
            max_seq = row["max_seq"] if row and row["max_seq"] is not None else 0
            new_user_id = f"RU{max_seq + 1:02d}"

            full_name = f"{first_name} {surname}".strip()
            dob = f"{year_of_birth}-01-01"
            hashed_password = _ph.hash(password)

            cur.execute(
                """
                INSERT INTO users (user_id, full_name, email, password, date_of_birth,
                                   secret_question, secret_answer, is_active)
                VALUES (%s, %s, %s, %s, %s::DATE, %s, %s, TRUE)
                """,
                (new_user_id, full_name, email, hashed_password, dob,
                 secret_question, secret_answer)
            )

            conn.commit()

        return (True, new_user_id)

    except psycopg2.errors.UniqueViolation:
        if conn:
            conn.rollback()
        return (False, f"Email '{email}' is already registered")

    except psycopg2.Error as exc:
        if conn:
            conn.rollback()
        return (False, f"Database error: {exc}")

    finally:
        if conn:
            conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """Verify credentials. Returns a user dict on success or None on failure."""
    sql = """
        SELECT user_id, full_name, email, phone, date_of_birth, is_active, password
        FROM users WHERE email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if row is None:
                return None
            if not row["is_active"]:
                return None

            try:
                _ph.verify(row["password"], password)
            except VerifyMismatchError:
                return None

            parts = row["full_name"].split(" ", 1)
            first_name = parts[0]
            surname = parts[1] if len(parts) > 1 else ""

            return {
                "user_id": row["user_id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "first_name": first_name,
                "surname": surname,
                "phone": row["phone"],
                "date_of_birth": str(row["date_of_birth"]) if row["date_of_birth"] else None,
                "is_active": row["is_active"],
            }


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT secret_question FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT secret_answer FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if not row or row[0] is None:
                return False
            return row[0].strip().lower() == answer.strip().lower()


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password = %s WHERE email = %s",
                (_ph.hash(new_password), email)
            )
            return cur.rowcount > 0


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """Find the most relevant policy documents for a given query embedding."""
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """Insert a policy document with its embedding into the database."""
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]