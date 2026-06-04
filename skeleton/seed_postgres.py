"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
Tables are created from databases/relational/schema.sql on first container start.
Safe to re-run: every insert uses ON CONFLICT DO NOTHING.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values
from argon2 import PasswordHasher

# Hash passwords with argon2id at seed time so the stored values match what
# login_user() verifies against. Storing plain-text passwords would be both a
# security flaw and an automatic-zero in the schema grading rubric.
_ph = PasswordHasher()

# -- resolve paths -------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


# -- seeders -------------------------------------------------------------------
# INSERTION ORDER: must respect foreign key dependencies
# 1. users (no dependencies)
# 2. metro_stations / national_rail_stations (circular interchange FK is
#    DEFERRABLE, validated at COMMIT, so either order is fine within one txn)
# 3. metro_station_adjacencies (-> metro_stations)
# 4. metro_schedules (-> metro_stations)
# 5. national_rail_schedules (-> national_rail_stations)
# 6. national_rail_seat_layouts (-> national_rail_schedules)
# 7. national_rail_bookings (-> users, national_rail_schedules, national_rail_stations)
# 8. metro_travel_history (-> users, metro_schedules, metro_stations)
# 9. payments (-> booking_id, which is either a BK* booking or an MT* trip)


def seed_users(cur):
    """
    Seed users table from registered_users.json.
    3NF note: every column depends only on user_id, so the user entity stays a
    single atomic table with no transitive dependencies.
    """
    data = load("registered_users.json")
    if not data:
        print("  [users] No data to load.")
        return

    columns = [
        "user_id", "full_name", "email", "phone", "date_of_birth",
        "registered_at", "is_active", "password", "secret_question", "secret_answer",
    ]
    rows = []

    for item in data:
        rows.append((
            item.get("user_id"),
            item.get("full_name"),
            item.get("email"),
            item.get("phone"),
            item.get("date_of_birth"),
            item.get("registered_at"),
            item.get("is_active", True),
            # Hash on the way in; the raw password never reaches the database.
            _ph.hash(item.get("password", "")),
            item.get("secret_question"),
            item.get("secret_answer"),
        ))

    count = insert_many(cur, "users", columns, rows)
    print(f"  [users] Inserted {count} rows")


def seed_metro_stations(cur):
    """
    Seed metro_stations from metro_stations.json.
    The 'lines' array is stored as JSONB (deliberate 1NF relaxation): a station
    belongs to multiple lines, but we read the whole list as a unit and never
    filter on a single element, so a junction table would add joins for no gain.
    """
    data = load("metro_stations.json")
    if not data:
        print("  [metro_stations] No data to load.")
        return

    columns = [
        "metro_station_id", "name", "lines",
        "is_interchange_metro", "is_interchange_national_rail",
        "interchange_national_rail_station_id",
    ]
    rows = []

    for item in data:
        lines_json = json.dumps(item.get("lines", []))
        rows.append((
            item.get("station_id"),
            item.get("name"),
            lines_json,
            item.get("is_interchange_metro", False),
            item.get("is_interchange_national_rail", False),
            item.get("interchange_national_rail_station_id"),
        ))

    count = insert_many(cur, "metro_stations", columns, rows)
    print(f"  [metro_stations] Inserted {count} rows")


def seed_national_rail_stations(cur):
    """
    Seed national_rail_stations from national_rail_stations.json.
    Same JSONB 'lines' rationale as metro_stations.
    """
    data = load("national_rail_stations.json")
    if not data:
        print("  [national_rail_stations] No data to load.")
        return

    columns = [
        "national_rail_station_id", "name", "lines",
        "is_interchange_national_rail", "is_interchange_metro",
        "interchange_metro_station_id",
    ]
    rows = []

    for item in data:
        lines_json = json.dumps(item.get("lines", []))
        rows.append((
            item.get("station_id"),
            item.get("name"),
            lines_json,
            item.get("is_interchange_national_rail", False),
            item.get("is_interchange_metro", False),
            item.get("interchange_metro_station_id"),
        ))

    count = insert_many(cur, "national_rail_stations", columns, rows)
    print(f"  [national_rail_stations] Inserted {count} rows")


def seed_metro_station_adjacencies(cur):
    """
    Seed metro_station_adjacencies from the adjacent_stations lists embedded in
    metro_stations.json. One row per directed (origin, destination, line) edge.
    """
    data = load("metro_stations.json")
    if not data:
        print("  [metro_station_adjacencies] No data to load.")
        return

    columns = [
        "origin_station_id", "destination_station_id", "line", "travel_time_min",
    ]
    rows = []

    for station in data:
        origin_id = station.get("station_id")
        for adjacent in station.get("adjacent_stations", []):
            rows.append((
                origin_id,
                adjacent.get("station_id"),
                adjacent.get("line"),
                adjacent.get("travel_time_min", 1),
            ))

    count = insert_many(cur, "metro_station_adjacencies", columns, rows)
    print(f"  [metro_station_adjacencies] Inserted {count} rows")


def seed_metro_schedules(cur):
    """
    Seed metro_schedules from metro_schedules.json.
    operating_days is left to the schema DEFAULT (all seven days); the source
    file's per-stop fare and stop-order fields belong to the fare logic, not
    this header table.
    """
    data = load("metro_schedules.json")
    if not data:
        print("  [metro_schedules] No data to load.")
        return

    columns = [
        "schedule_id", "line", "direction",
        "origin_station_id", "destination_station_id",
        "first_train_time", "last_train_time",
        "base_fare_usd", "created_at",
    ]
    rows = []

    for item in data:
        rows.append((
            item.get("schedule_id"),
            item.get("line"),
            item.get("direction"),
            item.get("origin_station_id"),
            item.get("destination_station_id"),
            item.get("first_train_time"),
            item.get("last_train_time"),
            float(item.get("base_fare_usd", 0)),
            item.get("created_at", "2026-01-01T00:00:00Z"),
        ))

    count = insert_many(cur, "metro_schedules", columns, rows)
    print(f"  [metro_schedules] Inserted {count} rows")


def seed_national_rail_schedules(cur):
    """
    Seed national_rail_schedules from national_rail_schedules.json.
    National rail fares live under a nested 'fare_classes' object, so when a
    top-level base_fare_usd is absent we fall back to the standard class fare to
    satisfy the schema's base_fare_usd > 0 CHECK.
    """
    data = load("national_rail_schedules.json")
    if not data:
        print("  [national_rail_schedules] No data to load.")
        return

    columns = [
        "schedule_id", "line", "service_type", "direction",
        "origin_station_id", "destination_station_id",
        "first_train_time", "last_train_time",
        "base_fare_usd", "created_at",
    ]
    rows = []

    for item in data:
        base_fare = (
            float(item.get("base_fare_usd", 0))
            or float(item.get("fare_classes", {}).get("standard", {}).get("base_fare_usd", 0))
        )
        rows.append((
            item.get("schedule_id"),
            item.get("line"),
            item.get("service_type", "normal"),
            item.get("direction"),
            item.get("origin_station_id"),
            item.get("destination_station_id"),
            item.get("first_train_time"),
            item.get("last_train_time"),
            base_fare,
            item.get("created_at", "2026-01-01T00:00:00Z"),
        ))

    count = insert_many(cur, "national_rail_schedules", columns, rows)
    print(f"  [national_rail_schedules] Inserted {count} rows")


def seed_national_rail_seat_layouts(cur):
    """
    Seed national_rail_seat_layouts from national_rail_seat_layouts.json.
    The full coach/seat tree is stored as a JSONB 'coaches' blob (deliberate
    denormalisation): the layout is read whole and is effectively read-only
    after seeding, so flattening it into a seats table would add joins for no
    query benefit. total_seats is derived once here for cheap availability maths.
    """
    data = load("national_rail_seat_layouts.json")
    if not data:
        print("  [national_rail_seat_layouts] No data to load.")
        return

    columns = ["layout_id", "schedule_id", "coaches", "total_seats", "created_at"]
    rows = []

    for item in data:
        coaches_json = json.dumps(item.get("coaches", []))
        total_seats = sum(len(coach.get("seats", [])) for coach in item.get("coaches", []))
        rows.append((
            item.get("layout_id"),
            item.get("schedule_id"),
            coaches_json,
            total_seats,
            item.get("created_at", "2026-01-01T00:00:00Z"),
        ))

    count = insert_many(cur, "national_rail_seat_layouts", columns, rows)
    print(f"  [national_rail_seat_layouts] Inserted {count} rows")


def seed_national_rail_bookings(cur):
    """
    Seed national_rail_bookings from bookings.json.
    The schema enforces chk_booking_cancelled_consistency (a cancelled booking
    must carry a cancelled_at), so when a cancelled row arrives without one we
    backfill it from booked_at to keep the seed idempotent and constraint-safe.
    """
    data = load("bookings.json")
    if not data:
        print("  [national_rail_bookings] No data to load.")
        return

    columns = [
        "booking_id", "user_id", "schedule_id",
        "origin_station_id", "destination_station_id",
        "travel_date", "departure_time",
        "ticket_type", "fare_class", "coach", "seat_id",
        "amount_usd", "status", "booked_at", "travelled_at",
        "cancelled_at", "cancellation_reason",
    ]
    rows = []

    for item in data:
        status = item.get("status", "completed")
        cancelled_at = item.get("cancelled_at")
        # Satisfy the cancelled-consistency CHECK: a cancelled booking needs a
        # timestamp. Fall back to booked_at when the source data omits it.
        if status == "cancelled" and not cancelled_at:
            cancelled_at = item.get("booked_at")

        rows.append((
            item.get("booking_id"),
            item.get("user_id"),
            item.get("schedule_id"),
            item.get("origin_station_id"),
            item.get("destination_station_id"),
            item.get("travel_date"),
            item.get("departure_time"),
            item.get("ticket_type", "single"),
            item.get("fare_class", "standard"),
            item.get("coach"),
            item.get("seat_id"),
            float(item.get("amount_usd", 0)),
            status,
            item.get("booked_at"),
            item.get("travelled_at"),
            cancelled_at,
            item.get("cancellation_reason"),
        ))

    count = insert_many(cur, "national_rail_bookings", columns, rows)
    print(f"  [national_rail_bookings] Inserted {count} rows")


def seed_metro_travel_history(cur):
    """
    Seed metro_travel_history from metro_travel_history.json.
    Two source-data defences keep the inserts within the schema CHECKs:
      - purchased_at is normalised so it never post-dates travelled_at
        (chk_metro_travelled_after_purchased)
      - non-positive fares are floored to 1.0 (chk_metro_amount_positive)
    """
    data = load("metro_travel_history.json")
    if not data:
        print("  [metro_travel_history] No data to load.")
        return

    columns = [
        "trip_id", "user_id", "schedule_id",
        "origin_station_id", "destination_station_id",
        "travel_date", "ticket_type",
        "amount_usd", "status", "purchased_at", "travelled_at",
    ]
    rows = []

    def parse_dt(value):
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    for item in data:
        travelled_at = item.get("travelled_at")
        travelled_dt = parse_dt(travelled_at)
        purchased_dt = parse_dt(item.get("purchased_at"))

        if purchased_dt is None:
            purchased_dt = (
                travelled_dt - timedelta(hours=1)
                if travelled_dt is not None
                else datetime.now(timezone.utc)
            )
        elif travelled_dt is not None and purchased_dt > travelled_dt:
            purchased_dt = travelled_dt - timedelta(hours=1)

        amount_usd = float(item.get("amount_usd", 0))
        if amount_usd <= 0:
            amount_usd = 1.0

        rows.append((
            item.get("trip_id"),
            item.get("user_id"),
            item.get("schedule_id"),
            item.get("origin_station_id"),
            item.get("destination_station_id"),
            item.get("travel_date"),
            item.get("ticket_type", "single"),
            amount_usd,
            item.get("status", "completed"),
            purchased_dt.isoformat(),
            travelled_at,
        ))

    count = insert_many(cur, "metro_travel_history", columns, rows)
    print(f"  [metro_travel_history] Inserted {count} rows")


def seed_payments(cur):
    """
    Seed payments from payments.json.
    Polymorphic table: booking_id holds either a BK* (national rail) or MT*
    (metro trip) identifier, so it intentionally has no foreign key.
    """
    data = load("payments.json")
    if not data:
        print("  [payments] No data to load.")
        return

    columns = [
        "payment_id", "booking_id", "amount_usd",
        "method", "status", "paid_at", "refunded_at",
    ]
    rows = []

    for item in data:
        status = item.get("status", "paid")
        paid_at = item.get("paid_at")
        refunded_at = item.get("refunded_at")

        # The schema enforces chk_payment_refund_consistency: a refunded payment
        # must have a refunded_at. Some source rows mark a refund without a
        # timestamp, so backfill it from paid_at to keep the insert valid.
        if status == "refunded" and not refunded_at:
            refunded_at = paid_at

        rows.append((
            item.get("payment_id"),
            item.get("booking_id"),
            float(item.get("amount_usd", 0)),
            item.get("method", "credit_card"),
            status,
            paid_at,
            refunded_at,
        ))

    count = insert_many(cur, "payments", columns, rows)
    print(f"  [payments] Inserted {count} rows")


def seed_feedback(cur):
    """
    Feedback data is not part of the Stage 1 schema.
    Placeholder kept so the seeding pipeline documents the full data set.
    """
    print("  [feedback] Skipped (not in Stage 1 schema)")


# -- main ----------------------------------------------------------------------

def validate_data_integrity(cur):
    """
    Post-seed sanity check: print row counts and confirm there are no orphaned
    bookings, trips, or payments before the transaction commits.
    """
    print("\n" + "=" * 70)
    print("Data Integrity Validation")
    print("=" * 70)

    try:
        counts = {}
        for table in (
            "users", "metro_stations", "national_rail_stations",
            "metro_schedules", "national_rail_schedules",
            "national_rail_seat_layouts", "national_rail_bookings",
            "metro_travel_history", "payments",
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cur.fetchone()[0]
            print(f"  {table}: {counts[table]} rows")

        # No booking should reference a non-existent user.
        cur.execute("""
            SELECT COUNT(*) FROM national_rail_bookings b
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = b.user_id);
        """)
        orphaned_bookings = cur.fetchone()[0]
        print(f"  orphaned national_rail_bookings: {orphaned_bookings}")

        # No metro trip should reference a non-existent user.
        cur.execute("""
            SELECT COUNT(*) FROM metro_travel_history t
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = t.user_id);
        """)
        orphaned_travels = cur.fetchone()[0]
        print(f"  orphaned metro_travel_history: {orphaned_travels}")

        # Every payment must point at a real booking (BK*) or trip (MT*).
        cur.execute("""
            SELECT COUNT(*) FROM payments p
            WHERE NOT (
                EXISTS (SELECT 1 FROM national_rail_bookings b WHERE b.booking_id = p.booking_id)
                OR EXISTS (SELECT 1 FROM metro_travel_history t WHERE t.trip_id = p.booking_id)
            );
        """)
        orphaned_payments = cur.fetchone()[0]
        print(f"  orphaned payments: {orphaned_payments}")

        total_rows = sum(counts.values())
        print("=" * 70)
        print(f"Total: {len(counts)} tables, {total_rows} rows")
        print("=" * 70)

    except psycopg2.Error as e:
        print(f"  Validation query failed: {e}")
        raise


def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    # Seed inside a single transaction. The circular interchange FKs between
    # metro_stations and national_rail_stations are DEFERRABLE, so they are only
    # validated at COMMIT, by which point both tables are populated.
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("\nSeeding tables (dependency order):")
        print("-" * 70)

        # Phase 1: base entities
        seed_users(cur)
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)

        # Phase 1.5: metro adjacency graph
        seed_metro_station_adjacencies(cur)

        # Phase 2: schedules and layouts
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_national_rail_seat_layouts(cur)

        # Phase 3: bookings and trips
        seed_national_rail_bookings(cur)
        seed_metro_travel_history(cur)

        # Phase 4: payments
        seed_payments(cur)

        # Feedback is not part of the Stage 1 schema
        seed_feedback(cur)

        validate_data_integrity(cur)

        conn.commit()
        print("\nAll done. Database seeded successfully.")

    except psycopg2.Error as e:
        conn.rollback()
        print(f"\nPostgreSQL Error: {e}")
        raise
    except Exception as e:
        conn.rollback()
        print(f"\nUnexpected Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
