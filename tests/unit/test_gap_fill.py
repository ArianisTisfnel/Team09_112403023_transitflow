"""
Unit tests for the gap-fill implementations identified in the 2.5 evaluation report.

Covers (all mocked — no live database required):
  - query_payment_info
  - register_user
  - login_user
  - get_user_secret_question
  - verify_secret_answer
  - update_password
  - query_station_connections (Neo4j)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from argon2 import PasswordHasher

_ph = PasswordHasher()
_ALICE_PW_HASH = _ph.hash("alice1990")


# ─────────────────────────────────────────────────────────────────
#  query_payment_info
# ─────────────────────────────────────────────────────────────────

class TestQueryPaymentInfo:
    def _make_row(self):
        return {
            "payment_id": "PM001",
            "booking_id": "BK001",
            "amount_usd": 8.50,
            "method": "credit_card",
            "status": "paid",
            "paid_at": "2026-04-01T10:16:00Z",
            "refunded_at": None,
        }

    def test_returns_dict_when_booking_exists(self):
        from databases.relational import queries

        row = self._make_row()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = row
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_payment_info("BK001")

        assert result == row

    def test_returns_none_when_not_found(self):
        from databases.relational import queries

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_payment_info("NOTEXIST")

        assert result is None

    def test_accepts_metro_trip_id(self):
        """booking_id for metro trips starts with 'MT'."""
        from databases.relational import queries

        row = {**self._make_row(), "booking_id": "MT001", "amount_usd": 1.40}
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = row
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_payment_info("MT001")

        assert result["booking_id"] == "MT001"


# ─────────────────────────────────────────────────────────────────
#  login_user
# ─────────────────────────────────────────────────────────────────

class TestLoginUser:
    def _db_row(self, **overrides):
        base = {
            "user_id": "RU01",
            "full_name": "Alice Tan",
            "email": "alice.tan@email.com",
            "phone": "07912340101",
            "date_of_birth": "1990-03-14",
            "is_active": True,
            "password": _ALICE_PW_HASH,
        }
        base.update(overrides)
        return base

    def _patch_connect(self, queries, row):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = row
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        ))

    def test_success_returns_user_dict(self):
        from databases.relational import queries
        with self._patch_connect(queries, self._db_row()):
            result = queries.login_user("alice.tan@email.com", "alice1990")

        assert result is not None
        assert result["user_id"] == "RU01"
        assert result["first_name"] == "Alice"
        assert result["surname"] == "Tan"
        assert result["email"] == "alice.tan@email.com"

    def test_wrong_password_returns_none(self):
        from databases.relational import queries
        with self._patch_connect(queries, self._db_row()):
            result = queries.login_user("alice.tan@email.com", "WRONG")

        assert result is None

    def test_email_not_found_returns_none(self):
        from databases.relational import queries
        with self._patch_connect(queries, None):
            result = queries.login_user("nobody@test.com", "pw")

        assert result is None

    def test_inactive_user_returns_none(self):
        from databases.relational import queries
        with self._patch_connect(queries, self._db_row(is_active=False)):
            result = queries.login_user("alice.tan@email.com", "alice1990")

        assert result is None

    def test_single_name_user(self):
        """full_name with no space: first_name = full word, surname = ''."""
        from databases.relational import queries
        with self._patch_connect(queries, self._db_row(full_name="Madonna")):
            result = queries.login_user("alice.tan@email.com", "alice1990")

        assert result["first_name"] == "Madonna"
        assert result["surname"] == ""

    def test_return_dict_has_required_keys(self):
        from databases.relational import queries
        with self._patch_connect(queries, self._db_row()):
            result = queries.login_user("alice.tan@email.com", "alice1990")

        required_keys = {"user_id", "email", "full_name", "first_name", "surname",
                         "phone", "date_of_birth", "is_active"}
        assert required_keys.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────
#  get_user_secret_question
# ─────────────────────────────────────────────────────────────────

class TestGetUserSecretQuestion:
    def test_returns_question_when_found(self):
        from databases.relational import queries

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("What was the name of your first pet?",)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        )):
            result = queries.get_user_secret_question("alice.tan@email.com")

        assert result == "What was the name of your first pet?"

    def test_returns_none_when_email_not_found(self):
        from databases.relational import queries

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        )):
            result = queries.get_user_secret_question("nobody@test.com")

        assert result is None


# ─────────────────────────────────────────────────────────────────
#  verify_secret_answer
# ─────────────────────────────────────────────────────────────────

class TestVerifySecretAnswer:
    def _patch(self, queries, stored_answer):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (stored_answer,) if stored_answer is not None else None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        ))

    def test_correct_answer_exact_case(self):
        from databases.relational import queries
        with self._patch(queries, "Biscuit"):
            assert queries.verify_secret_answer("alice.tan@email.com", "Biscuit") is True

    def test_correct_answer_case_insensitive(self):
        from databases.relational import queries
        with self._patch(queries, "Biscuit"):
            assert queries.verify_secret_answer("alice.tan@email.com", "biscuit") is True

    def test_correct_answer_with_whitespace(self):
        from databases.relational import queries
        with self._patch(queries, "Maple Avenue"):
            assert queries.verify_secret_answer("x@x.com", "  maple avenue  ") is True

    def test_wrong_answer_returns_false(self):
        from databases.relational import queries
        with self._patch(queries, "Biscuit"):
            assert queries.verify_secret_answer("alice.tan@email.com", "Cookie") is False

    def test_user_not_found_returns_false(self):
        from databases.relational import queries
        with self._patch(queries, None):
            assert queries.verify_secret_answer("nobody@test.com", "anything") is False


# ─────────────────────────────────────────────────────────────────
#  update_password
# ─────────────────────────────────────────────────────────────────

class TestUpdatePassword:
    def _patch(self, queries, rowcount):
        mock_cur = MagicMock()
        mock_cur.rowcount = rowcount
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return patch.object(queries, "_connect", return_value=MagicMock(
            __enter__=lambda s: mock_conn, __exit__=MagicMock(return_value=False)
        ))

    def test_returns_true_when_row_updated(self):
        from databases.relational import queries
        with self._patch(queries, 1):
            assert queries.update_password("alice.tan@email.com", "newpw") is True

    def test_returns_false_when_email_not_found(self):
        from databases.relational import queries
        with self._patch(queries, 0):
            assert queries.update_password("nobody@test.com", "pw") is False


# ─────────────────────────────────────────────────────────────────
#  register_user
# ─────────────────────────────────────────────────────────────────

class TestRegisterUserUnit:
    """Unit tests using a mocked DB connection."""

    def _make_conn(self, fetchone_seq: list):
        """Return a mock psycopg2 connection whose cursor.fetchone() returns
        values from fetchone_seq in order."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = fetchone_seq
        mock_cur.rowcount = 1

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cur

    def test_success_returns_true_and_user_id(self):
        from databases.relational import queries
        import psycopg2

        mock_conn, _ = self._make_conn([
            None,                        # no duplicate email
            {"max_seq": 20},             # MAX sequence → RU21
        ])

        with patch("psycopg2.connect", return_value=mock_conn):
            ok, uid = queries.register_user(
                "new@test.com", "New", "User", 1995,
                "pw", "q?", "ans"
            )

        assert ok is True
        assert uid == "RU21"

    def test_duplicate_email_returns_false(self):
        from databases.relational import queries

        mock_conn, _ = self._make_conn([
            {"user_id": "RU01"},         # duplicate email found
        ])

        with patch("psycopg2.connect", return_value=mock_conn):
            ok, msg = queries.register_user(
                "alice.tan@email.com", "Alice", "Tan", 1990,
                "pw", "q?", "ans"
            )

        assert ok is False
        assert "already registered" in msg

    def test_first_user_gets_ru01(self):
        from databases.relational import queries

        mock_conn, _ = self._make_conn([
            None,                        # no duplicate
            {"max_seq": None},           # no existing RU users
        ])

        with patch("psycopg2.connect", return_value=mock_conn):
            ok, uid = queries.register_user(
                "first@test.com", "First", "Last", 2000,
                "pw", "q", "a"
            )

        assert ok is True
        assert uid == "RU01"

    def test_full_name_composed_correctly(self):
        """Verify full_name = 'first_name surname' is passed to INSERT."""
        from databases.relational import queries

        mock_conn, mock_cur = self._make_conn([
            None,
            {"max_seq": 5},
        ])

        with patch("psycopg2.connect", return_value=mock_conn):
            queries.register_user("x@x.com", "John", "Smith", 1985,
                                  "pw", "q", "a")

        # Inspect the INSERT call args
        insert_call = mock_cur.execute.call_args_list[-1]
        params = insert_call[0][1]          # positional args tuple
        assert params[1] == "John Smith"    # full_name is second param


# ─────────────────────────────────────────────────────────────────
#  query_station_connections (Neo4j)
# ─────────────────────────────────────────────────────────────────

class TestQueryStationConnections:
    def _make_records(self):
        return [
            {
                "from_station_id": "MS01", "from_station_name": "Central Square",
                "from_network": "metro",
                "to_station_id": "MS02",   "to_station_name": "Riverside",
                "to_network": "metro",
                "relationship_type": "CONNECTS_TO",
                "travel_time_min": 3,       "line": "M1",
            },
            {
                "from_station_id": "MS01", "from_station_name": "Central Square",
                "from_network": "metro",
                "to_station_id": "NR01",   "to_station_name": "Central Station",
                "to_network": "rail",
                "relationship_type": "INTERCHANGE",
                "travel_time_min": None,    "line": None,
            },
        ]

    def test_returns_list_of_connections(self):
        from databases.graph import queries

        records = self._make_records()
        mock_session = MagicMock()
        mock_session.run.return_value.data.return_value = records
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "get_pool", return_value=MagicMock(
            __enter__=lambda s: mock_driver, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_station_connections("MS01")

        assert len(result) == 2
        assert result[0]["to_station_id"] == "MS02"
        assert result[0]["relationship_type"] == "CONNECTS_TO"
        assert result[1]["relationship_type"] == "INTERCHANGE"

    def test_returns_empty_list_for_unknown_station(self):
        from databases.graph import queries

        mock_session = MagicMock()
        mock_session.run.return_value.data.return_value = []
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "get_pool", return_value=MagicMock(
            __enter__=lambda s: mock_driver, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_station_connections("INVALID")

        assert result == []

    def test_exception_returns_empty_list(self):
        from databases.graph import queries

        with patch.object(queries, "get_pool", side_effect=RuntimeError("neo4j down")):
            result = queries.query_station_connections("MS01")

        assert result == []

    def test_connection_has_required_keys(self):
        from databases.graph import queries

        records = self._make_records()[:1]
        mock_session = MagicMock()
        mock_session.run.return_value.data.return_value = records
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(queries, "get_pool", return_value=MagicMock(
            __enter__=lambda s: mock_driver, __exit__=MagicMock(return_value=False)
        )):
            result = queries.query_station_connections("MS01")

        required = {"from_station_id", "from_station_name", "from_network",
                    "to_station_id", "to_station_name", "to_network",
                    "relationship_type", "travel_time_min", "line"}
        assert required.issubset(result[0].keys())
