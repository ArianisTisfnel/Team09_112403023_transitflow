"""
Unit tests for Stage 2.4 — skeleton/maintenance_check.py

DoD coverage:
  - check_orphan_bookings detects bookings with missing user_id
  - check_schedule_time_logic detects first_train_time >= last_train_time
  - check_capacity_consistency detects booking count > total_seats
  - run_checks sets READ ONLY transaction and aggregates all three checks
  - overall_status is FAIL when any sub-check fails; PASS when all pass
  - report has required top-level keys and summary counts
  - repair SQL is generated but run_checks never executes it (read-only guarantee)
  - apply_repairs executes SQL only when called explicitly
  - datetime/date/time values in records are serialized to ISO strings
"""

import json
from datetime import date, time, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from skeleton.maintenance_check import (
    apply_repairs,
    check_capacity_consistency,
    check_orphan_bookings,
    check_schedule_time_logic,
    run_checks,
)


# ── mock cursor factory ───────────────────────────────────────────────────────

def _make_cur(fetchall_return=None, fetchone_return=None):
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_return or []
    cur.fetchone.return_value = fetchone_return
    return cur


def _make_conn(mock_cur):
    """Return a mock connection whose cursor() context-manager yields mock_cur."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = mock_cur
    return conn


# ═════════════════════════════════════════════════════════════════════════════
# check_orphan_bookings
# ═════════════════════════════════════════════════════════════════════════════

_ORPHAN_ROW = {
    "booking_id": "BK001",
    "user_id": "USR_DELETED",
    "schedule_id": "NR_SCH01",
    "travel_date": date(2025, 6, 1),
    "status": "confirmed",
    "booked_at": datetime(2025, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
}


def test_orphan_check_status_fail_when_orphans_exist():
    """FAIL status when at least one orphan booking is found."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    assert result["status"] == "FAIL"


def test_orphan_check_status_pass_when_no_orphans():
    """PASS status when query returns no rows."""
    cur = _make_cur(fetchall_return=[])
    result = check_orphan_bookings(cur)
    assert result["status"] == "PASS"
    assert result["count"] == 0
    assert result["records"] == []


def test_orphan_check_count_matches_row_count():
    """count must equal the number of orphan rows returned by the query."""
    rows = [dict(_ORPHAN_ROW, booking_id=f"BK{i:03d}") for i in range(3)]
    cur = _make_cur(fetchall_return=rows)
    result = check_orphan_bookings(cur)
    assert result["count"] == 3


def test_orphan_check_records_contain_booking_and_user_id():
    """Each record must contain booking_id and user_id fields."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    record = result["records"][0]
    assert "booking_id" in record
    assert "user_id" in record
    assert record["booking_id"] == "BK001"
    assert record["user_id"] == "USR_DELETED"


def test_orphan_check_dates_serialized_to_strings():
    """date and datetime values in records must be ISO-format strings (JSON-safe)."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    record = result["records"][0]
    assert isinstance(record["travel_date"], str)
    assert isinstance(record["booked_at"], str)
    # Verify round-trip to JSON without error
    json.dumps(result)


def test_orphan_check_repair_sql_targets_correct_booking():
    """Repair SQL must reference the specific booking_id."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    assert len(result["repair_sql"]) == 1
    sql = result["repair_sql"][0]
    assert "BK001" in sql


def test_orphan_check_repair_sql_sets_cancelled_status():
    """Repair SQL must set status = 'cancelled' (within FK constraint)."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    sql = result["repair_sql"][0]
    assert "cancelled" in sql.lower()


def test_orphan_check_repair_sql_includes_integrity_marker():
    """Repair SQL reason must contain a DATA_INTEGRITY marker."""
    cur = _make_cur(fetchall_return=[_ORPHAN_ROW.copy()])
    result = check_orphan_bookings(cur)
    sql = result["repair_sql"][0]
    assert "DATA_INTEGRITY" in sql


def test_orphan_check_required_keys():
    """Result dict must contain check, status, count, records, repair_sql keys."""
    cur = _make_cur(fetchall_return=[])
    result = check_orphan_bookings(cur)
    for key in ("check", "description", "status", "count", "records", "repair_sql"):
        assert key in result, f"Missing key: {key}"


# ═════════════════════════════════════════════════════════════════════════════
# check_schedule_time_logic — DoD 1: detect departure >= arrival
# ═════════════════════════════════════════════════════════════════════════════

_BAD_SCHEDULE_ROW = {
    "schedule_id": "NR_SCH_BAD",
    "line": "NR1",
    "service_type": "express",
    "direction": "northbound",
    "origin_station_id": "NR01",
    "destination_station_id": "NR05",
    "first_train_time": time(18, 0),   # departure AFTER arrival
    "last_train_time": time(9, 0),
}


def test_time_check_detects_inverted_schedule():
    """DoD 1: script must detect a schedule where first_train >= last_train."""
    cur = _make_cur(fetchall_return=[_BAD_SCHEDULE_ROW.copy()])
    result = check_schedule_time_logic(cur)
    assert result["status"] == "FAIL"
    assert result["count"] == 1
    assert result["records"][0]["schedule_id"] == "NR_SCH_BAD"


def test_time_check_pass_when_all_schedules_valid():
    """PASS when no inverted schedules found."""
    cur = _make_cur(fetchall_return=[])
    result = check_schedule_time_logic(cur)
    assert result["status"] == "PASS"
    assert result["count"] == 0


def test_time_check_records_include_both_time_fields():
    """Records must include first_train_time and last_train_time for diagnosis."""
    cur = _make_cur(fetchall_return=[_BAD_SCHEDULE_ROW.copy()])
    result = check_schedule_time_logic(cur)
    record = result["records"][0]
    assert "first_train_time" in record
    assert "last_train_time" in record


def test_time_check_time_fields_serialized_to_strings():
    """time values must be ISO-format strings for JSON serialization."""
    cur = _make_cur(fetchall_return=[_BAD_SCHEDULE_ROW.copy()])
    result = check_schedule_time_logic(cur)
    record = result["records"][0]
    assert isinstance(record["first_train_time"], str)
    assert isinstance(record["last_train_time"], str)
    json.dumps(result)


def test_time_check_repair_sql_references_schedule_id():
    """Repair SQL must reference the invalid schedule_id."""
    cur = _make_cur(fetchall_return=[_BAD_SCHEDULE_ROW.copy()])
    result = check_schedule_time_logic(cur)
    assert len(result["repair_sql"]) == 1
    sql = result["repair_sql"][0]
    assert "NR_SCH_BAD" in sql


def test_time_check_repair_sql_offers_delete_option():
    """Repair SQL must include a DELETE statement as the safe default fix."""
    cur = _make_cur(fetchall_return=[_BAD_SCHEDULE_ROW.copy()])
    result = check_schedule_time_logic(cur)
    sql = result["repair_sql"][0]
    assert "DELETE" in sql.upper()


def test_time_check_required_keys():
    """Result dict must contain required keys."""
    cur = _make_cur(fetchall_return=[])
    result = check_schedule_time_logic(cur)
    for key in ("check", "description", "status", "count", "records", "repair_sql"):
        assert key in result


# ═════════════════════════════════════════════════════════════════════════════
# check_capacity_consistency — DoD 3: pinpoint over-capacity schedule_id
# ═════════════════════════════════════════════════════════════════════════════

_OVER_CAPACITY_ROW = {
    "schedule_id": "NR_SCH_FULL",
    "layout_id": "LAY001",
    "total_seats": 50,
    "booking_count": 55,
    "overflow": 5,
}


def test_capacity_check_detects_overbooked_schedule():
    """DoD 3: capacity check must identify the exact schedule_id that is over capacity."""
    cur = _make_cur(fetchall_return=[_OVER_CAPACITY_ROW.copy()])
    result = check_capacity_consistency(cur)
    assert result["status"] == "FAIL"
    assert result["count"] == 1
    assert result["records"][0]["schedule_id"] == "NR_SCH_FULL"


def test_capacity_check_pass_when_within_limits():
    """PASS when no schedule exceeds its seat layout."""
    cur = _make_cur(fetchall_return=[])
    result = check_capacity_consistency(cur)
    assert result["status"] == "PASS"
    assert result["count"] == 0


def test_capacity_check_records_contain_overflow_field():
    """Records must include overflow (booking_count - total_seats) for quick diagnosis."""
    cur = _make_cur(fetchall_return=[_OVER_CAPACITY_ROW.copy()])
    result = check_capacity_consistency(cur)
    record = result["records"][0]
    assert "overflow" in record
    assert int(record["overflow"]) == 5


def test_capacity_check_repair_sql_references_schedule_id():
    """Repair SQL must reference the over-capacity schedule_id."""
    cur = _make_cur(fetchall_return=[_OVER_CAPACITY_ROW.copy()])
    result = check_capacity_consistency(cur)
    assert len(result["repair_sql"]) == 1
    sql = result["repair_sql"][0]
    assert "NR_SCH_FULL" in sql


def test_capacity_check_repair_sql_cancels_overflow_count():
    """Repair SQL LIMIT must match the overflow count (5 in this case)."""
    cur = _make_cur(fetchall_return=[_OVER_CAPACITY_ROW.copy()])
    result = check_capacity_consistency(cur)
    sql = result["repair_sql"][0]
    assert "LIMIT 5" in sql


def test_capacity_check_repair_sql_targets_cancelled_status():
    """Repair SQL must cancel excess bookings (not delete them)."""
    cur = _make_cur(fetchall_return=[_OVER_CAPACITY_ROW.copy()])
    result = check_capacity_consistency(cur)
    sql = result["repair_sql"][0]
    assert "cancelled" in sql.lower()


def test_capacity_check_required_keys():
    """Result dict must contain required keys."""
    cur = _make_cur(fetchall_return=[])
    result = check_capacity_consistency(cur)
    for key in ("check", "description", "status", "count", "records", "repair_sql"):
        assert key in result


# ═════════════════════════════════════════════════════════════════════════════
# run_checks — orchestration and read-only guarantee
# ═════════════════════════════════════════════════════════════════════════════

def _setup_run_checks_mock(orphan_rows=None, time_rows=None, capacity_rows=None):
    """
    Wire a mock connection so run_checks() gets a cursor whose fetchall
    returns the three sets of rows in call order.
    """
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        orphan_rows   or [],
        time_rows     or [],
        capacity_rows or [],
    ]
    conn = _make_conn(mock_cur)
    return conn, mock_cur


def test_run_checks_sets_read_only_transaction():
    """run_checks must issue SET TRANSACTION READ ONLY before any query."""
    conn, mock_cur = _setup_run_checks_mock()
    run_checks(conn)
    first_call_sql = mock_cur.execute.call_args_list[0][0][0]
    assert "READ ONLY" in first_call_sql.upper()


def test_run_checks_overall_pass_when_all_checks_pass():
    """overall_status is PASS when all three checks return no violations."""
    conn, _ = _setup_run_checks_mock()
    report = run_checks(conn)
    assert report["overall_status"] == "PASS"


def test_run_checks_overall_fail_when_orphans_found():
    """overall_status is FAIL when orphan bookings are detected."""
    conn, _ = _setup_run_checks_mock(orphan_rows=[_ORPHAN_ROW.copy()])
    report = run_checks(conn)
    assert report["overall_status"] == "FAIL"


def test_run_checks_overall_fail_when_bad_schedule_found():
    """overall_status is FAIL when invalid schedule time is detected."""
    conn, _ = _setup_run_checks_mock(time_rows=[_BAD_SCHEDULE_ROW.copy()])
    report = run_checks(conn)
    assert report["overall_status"] == "FAIL"


def test_run_checks_overall_fail_when_over_capacity_found():
    """overall_status is FAIL when a schedule exceeds capacity."""
    conn, _ = _setup_run_checks_mock(capacity_rows=[_OVER_CAPACITY_ROW.copy()])
    report = run_checks(conn)
    assert report["overall_status"] == "FAIL"


def test_run_checks_summary_counts_match_individual_check_counts():
    """summary dict must reflect the count from each sub-check."""
    conn, _ = _setup_run_checks_mock(
        orphan_rows=[_ORPHAN_ROW.copy()],
        time_rows=[],
        capacity_rows=[_OVER_CAPACITY_ROW.copy()],
    )
    report = run_checks(conn)
    s = report["summary"]
    assert s["orphan_bookings"] == 1
    assert s["invalid_time_schedules"] == 0
    assert s["over_capacity_schedules"] == 1


def test_run_checks_report_has_required_top_level_keys():
    """Report must contain report_generated_at, overall_status, checks, summary."""
    conn, _ = _setup_run_checks_mock()
    report = run_checks(conn)
    for key in ("report_generated_at", "overall_status", "checks", "summary"):
        assert key in report, f"Missing top-level key: {key}"


def test_run_checks_contains_three_check_entries():
    """checks list must have exactly 3 entries (one per check type)."""
    conn, _ = _setup_run_checks_mock()
    report = run_checks(conn)
    assert len(report["checks"]) == 3


def test_run_checks_check_names_are_correct():
    """Each checks entry must have the expected 'check' name."""
    conn, _ = _setup_run_checks_mock()
    report = run_checks(conn)
    names = [c["check"] for c in report["checks"]]
    assert "orphan_bookings" in names
    assert "schedule_time_logic" in names
    assert "capacity_consistency" in names


def test_run_checks_report_is_json_serializable():
    """The full report must serialize to JSON without error (UI-ready output)."""
    conn, _ = _setup_run_checks_mock(
        orphan_rows=[_ORPHAN_ROW.copy()],
        time_rows=[_BAD_SCHEDULE_ROW.copy()],
        capacity_rows=[_OVER_CAPACITY_ROW.copy()],
    )
    report = run_checks(conn)
    # Must not raise
    json.dumps(report, default=str)


def test_run_checks_does_not_commit_or_write(monkeypatch):
    """run_checks must never call conn.commit() — it is strictly read-only."""
    conn, _ = _setup_run_checks_mock()
    run_checks(conn)
    conn.commit.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# apply_repairs — explicit call only
# ═════════════════════════════════════════════════════════════════════════════

def _build_report_with_repair_sql(sql_statements: list[str]) -> dict:
    """Build a minimal report dict containing the given repair SQL strings."""
    return {
        "checks": [
            {
                "check": "orphan_bookings",
                "repair_sql": sql_statements,
            }
        ]
    }


def test_apply_repairs_executes_non_comment_sql():
    """apply_repairs must execute each non-comment SQL line from repair_sql."""
    sql = "UPDATE national_rail_bookings SET status = 'cancelled' WHERE booking_id = 'BK001';"
    report = _build_report_with_repair_sql([sql])

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    result = apply_repairs(conn, report)
    assert result["executed_count"] == 1
    assert result["failed_count"] == 0


def test_apply_repairs_commits_on_success():
    """apply_repairs must commit after successful execution."""
    sql = "UPDATE national_rail_bookings SET status = 'cancelled' WHERE booking_id = 'BK002';"
    report = _build_report_with_repair_sql([sql])

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    apply_repairs(conn, report)
    conn.commit.assert_called_once()


def test_apply_repairs_skips_comment_only_entries():
    """Repair SQL entries that are entirely comments must not be executed."""
    sql = "-- This is a comment only\n-- Another comment"
    report = _build_report_with_repair_sql([sql])

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    result = apply_repairs(conn, report)
    cur.execute.assert_not_called()
    assert result["executed_count"] == 0


def test_apply_repairs_rollback_on_failure():
    """apply_repairs must rollback and record failure when SQL raises an exception."""
    sql = "UPDATE national_rail_bookings SET status = 'cancelled' WHERE booking_id = 'BK_ERR';"
    report = _build_report_with_repair_sql([sql])

    conn = MagicMock()
    cur = MagicMock()
    cur.execute.side_effect = Exception("syntax error")
    conn.cursor.return_value.__enter__.return_value = cur

    result = apply_repairs(conn, report)
    conn.rollback.assert_called()
    assert result["failed_count"] == 1
    assert result["executed_count"] == 0


def test_apply_repairs_result_has_required_keys():
    """apply_repairs result must contain repair_applied_at, executed_count, failed_count, failures."""
    report = _build_report_with_repair_sql([])
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    result = apply_repairs(conn, report)
    for key in ("repair_applied_at", "executed_count", "failed_count", "failures"):
        assert key in result, f"Missing key: {key}"


if __name__ == "__main__":
    # Quick smoke-run without pytest
    tests = [
        test_orphan_check_status_fail_when_orphans_exist,
        test_orphan_check_status_pass_when_no_orphans,
        test_orphan_check_count_matches_row_count,
        test_orphan_check_records_contain_booking_and_user_id,
        test_orphan_check_dates_serialized_to_strings,
        test_orphan_check_repair_sql_targets_correct_booking,
        test_orphan_check_repair_sql_sets_cancelled_status,
        test_orphan_check_repair_sql_includes_integrity_marker,
        test_orphan_check_required_keys,
        test_time_check_detects_inverted_schedule,
        test_time_check_pass_when_all_schedules_valid,
        test_time_check_records_include_both_time_fields,
        test_time_check_time_fields_serialized_to_strings,
        test_time_check_repair_sql_references_schedule_id,
        test_time_check_repair_sql_offers_delete_option,
        test_time_check_required_keys,
        test_capacity_check_detects_overbooked_schedule,
        test_capacity_check_pass_when_within_limits,
        test_capacity_check_records_contain_overflow_field,
        test_capacity_check_repair_sql_references_schedule_id,
        test_capacity_check_repair_sql_cancels_overflow_count,
        test_capacity_check_repair_sql_targets_cancelled_status,
        test_capacity_check_required_keys,
        test_run_checks_sets_read_only_transaction,
        test_run_checks_overall_pass_when_all_checks_pass,
        test_run_checks_overall_fail_when_orphans_found,
        test_run_checks_overall_fail_when_bad_schedule_found,
        test_run_checks_overall_fail_when_over_capacity_found,
        test_run_checks_summary_counts_match_individual_check_counts,
        test_run_checks_report_has_required_top_level_keys,
        test_run_checks_contains_three_check_entries,
        test_run_checks_check_names_are_correct,
        test_run_checks_report_is_json_serializable,
        test_run_checks_does_not_commit_or_write,
        test_apply_repairs_executes_non_comment_sql,
        test_apply_repairs_commits_on_success,
        test_apply_repairs_skips_comment_only_entries,
        test_apply_repairs_rollback_on_failure,
        test_apply_repairs_result_has_required_keys,
    ]
    for t in tests:
        if "monkeypatch" in t.__code__.co_varnames:
            continue  # skip pytest-fixture tests in smoke mode
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\n✓ All {len(tests) - 1} smoke tests passed")
