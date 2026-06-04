"""
Integration tests for the gap-fill implementations (2.5 evaluation report).

Requires live Docker services:
  - PostgreSQL  → localhost:5433
  - Neo4j       → localhost:7688

Run with: pytest tests/integration/test_phase_2.5_gap_fill_integration.py -v
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest


# ─── helpers ──────────────────────────────────────────────────────────────────

def _pg():
    return psycopg2.connect(
        host="localhost", port=5433, dbname="transitflow",
        user="transitflow", password="transitflow",
    )


def _delete_user(email: str) -> None:
    conn = _pg()
    conn.autocommit = True
    conn.cursor().execute("DELETE FROM users WHERE email = %s", (email,))
    conn.close()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def temp_email():
    """Yield a unique email and clean up after the test."""
    email = f"test_{uuid.uuid4().hex[:8]}@integtest.com"
    yield email
    _delete_user(email)


# ─────────────────────────────────────────────────────────────────────────────
#  query_payment_info
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryPaymentInfoIntegration:
    def test_returns_payment_for_existing_booking(self):
        from databases.relational.queries import query_payment_info
        result = query_payment_info("BK001")
        assert result is not None
        assert result["booking_id"] == "BK001"
        assert result["payment_id"] == "PM001"
        assert float(result["amount_usd"]) == pytest.approx(8.50)
        assert result["method"] == "credit_card"
        assert result["status"] == "paid"

    def test_returns_payment_for_metro_trip(self):
        from databases.relational.queries import query_payment_info
        result = query_payment_info("MT001")
        assert result is not None
        assert result["booking_id"] == "MT001"
        assert result["payment_id"] == "PM002"

    def test_returns_none_for_nonexistent_booking(self):
        from databases.relational.queries import query_payment_info
        result = query_payment_info("BK-NONEXISTENT-9999")
        assert result is None

    def test_refunded_payment_has_refunded_status(self):
        from databases.relational.queries import query_payment_info
        # BK003 has a refunded payment (PM005)
        result = query_payment_info("BK003")
        assert result is not None
        assert result["status"] == "refunded"

    def test_result_has_all_expected_keys(self):
        from databases.relational.queries import query_payment_info
        result = query_payment_info("BK001")
        expected_keys = {"payment_id", "booking_id", "amount_usd",
                         "method", "status", "paid_at", "refunded_at"}
        assert expected_keys.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────────────────
#  register_user
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterUserIntegration:
    def test_successful_registration(self, temp_email):
        from databases.relational.queries import register_user
        ok, uid = register_user(
            email=temp_email,
            first_name="Integration",
            surname="Tester",
            year_of_birth=1990,
            password="testpw123",
            secret_question="Favourite colour?",
            secret_answer="Blue",
        )
        assert ok is True
        assert uid.startswith("RU")
        assert uid[2:].isdigit()

    def test_user_appears_in_db_after_registration(self, temp_email):
        from databases.relational.queries import register_user
        ok, uid = register_user(
            email=temp_email, first_name="DB", surname="Check",
            year_of_birth=1985, password="pw", secret_question="q", secret_answer="a",
        )
        assert ok is True

        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT user_id, full_name, email FROM users WHERE email = %s", (temp_email,))
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == uid
        assert row[1] == "DB Check"

    def test_duplicate_email_returns_false(self, temp_email):
        from databases.relational.queries import register_user
        ok1, _ = register_user(
            email=temp_email, first_name="First", surname="User",
            year_of_birth=1990, password="pw1", secret_question="q", secret_answer="a",
        )
        assert ok1 is True

        ok2, msg = register_user(
            email=temp_email, first_name="Second", surname="User",
            year_of_birth=1991, password="pw2", secret_question="q2", secret_answer="a2",
        )
        assert ok2 is False
        assert "already registered" in msg

    def test_year_stored_as_date(self, temp_email):
        """date_of_birth should be stored as YYYY-01-01."""
        from databases.relational.queries import register_user
        register_user(
            email=temp_email, first_name="Year", surname="Test",
            year_of_birth=1992, password="pw", secret_question="q", secret_answer="a",
        )
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT date_of_birth FROM users WHERE email = %s", (temp_email,))
        row = cur.fetchone()
        conn.close()

        assert row[0].year == 1992
        assert row[0].month == 1
        assert row[0].day == 1


# ─────────────────────────────────────────────────────────────────────────────
#  login_user
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginUserIntegration:
    def test_correct_credentials_return_user_dict(self):
        from databases.relational.queries import login_user
        result = login_user("alice.tan@email.com", "alice1990")
        assert result is not None
        assert result["user_id"] == "RU01"
        assert result["first_name"] == "Alice"
        assert result["surname"] == "Tan"
        assert result["is_active"] is True

    def test_wrong_password_returns_none(self):
        from databases.relational.queries import login_user
        assert login_user("alice.tan@email.com", "WRONGPASSWORD") is None

    def test_nonexistent_email_returns_none(self):
        from databases.relational.queries import login_user
        assert login_user("nobody_at_all@example.com", "pw") is None

    def test_inactive_user_returns_none(self):
        """RU05 (Emma Soh) has is_active = false."""
        from databases.relational.queries import login_user
        assert login_user("emma.soh@email.com", "Emma2000!") is None

    def test_result_contains_all_required_keys(self):
        from databases.relational.queries import login_user
        result = login_user("alice.tan@email.com", "alice1990")
        required = {"user_id", "email", "full_name", "first_name", "surname",
                    "phone", "date_of_birth", "is_active"}
        assert required.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────────────────
#  get_user_secret_question
# ─────────────────────────────────────────────────────────────────────────────

class TestGetUserSecretQuestionIntegration:
    def test_returns_question_for_alice(self):
        from databases.relational.queries import get_user_secret_question
        q = get_user_secret_question("alice.tan@email.com")
        assert q == "What was the name of your first pet?"

    def test_returns_none_for_unknown_email(self):
        from databases.relational.queries import get_user_secret_question
        assert get_user_secret_question("ghost@test.com") is None


# ─────────────────────────────────────────────────────────────────────────────
#  verify_secret_answer
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifySecretAnswerIntegration:
    def test_correct_answer_exact(self):
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("alice.tan@email.com", "Biscuit") is True

    def test_correct_answer_lowercase(self):
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("alice.tan@email.com", "biscuit") is True

    def test_correct_answer_with_leading_trailing_spaces(self):
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("alice.tan@email.com", "  Biscuit  ") is True

    def test_wrong_answer_returns_false(self):
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("alice.tan@email.com", "WrongAnswer") is False

    def test_unknown_email_returns_false(self):
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("ghost@test.com", "anything") is False

    def test_multiword_answer(self):
        """Clara's answer is 'Maple Avenue'."""
        from databases.relational.queries import verify_secret_answer
        assert verify_secret_answer("clara.wong@email.com", "maple avenue") is True


# ─────────────────────────────────────────────────────────────────────────────
#  update_password
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdatePasswordIntegration:
    def test_update_then_login_with_new_password(self, temp_email):
        from databases.relational.queries import register_user, update_password, login_user

        register_user(
            email=temp_email, first_name="Pw", surname="Test",
            year_of_birth=1990, password="original_pw",
            secret_question="q", secret_answer="a",
        )
        assert update_password(temp_email, "new_secure_pw") is True

        # Old password should fail
        assert login_user(temp_email, "original_pw") is None
        # New password should succeed
        assert login_user(temp_email, "new_secure_pw") is not None

    def test_update_nonexistent_email_returns_false(self):
        from databases.relational.queries import update_password
        assert update_password("ghost_nobody@test.com", "pw") is False


# ─────────────────────────────────────────────────────────────────────────────
#  query_station_connections (Neo4j)
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryStationConnectionsIntegration:
    def test_ms01_has_multiple_connections(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        assert isinstance(result, list)
        assert len(result) >= 4   # MS01 connects to MS02, MS05, MS06, MS07, NR01

    def test_ms01_has_connects_to_relationships(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        types = {r["relationship_type"] for r in result}
        assert "CONNECTS_TO" in types

    def test_ms01_has_interchange_to_nr01(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        interchange = [r for r in result if r["relationship_type"] == "INTERCHANGE"]
        assert any(r["to_station_id"] == "NR01" for r in interchange)

    def test_each_connection_has_required_keys(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        required = {"from_station_id", "from_station_name", "from_network",
                    "to_station_id", "to_station_name", "to_network",
                    "relationship_type", "travel_time_min", "line"}
        for conn in result:
            assert required.issubset(conn.keys()), f"Missing keys in: {conn}"

    def test_connects_to_relationships_have_travel_time(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        for conn in result:
            if conn["relationship_type"] == "CONNECTS_TO":
                assert conn["travel_time_min"] is not None
                assert conn["travel_time_min"] > 0

    def test_unknown_station_returns_empty_list(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("STATION_DOES_NOT_EXIST")
        assert result == []

    def test_nr01_connects_to_rail_stations(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("NR01")
        # network_type for national rail nodes is "national_rail"
        rail_neighbors = [r for r in result if r["to_network"] == "national_rail"]
        assert len(rail_neighbors) >= 1

    def test_result_is_sorted_by_station_id(self):
        from databases.graph.queries import query_station_connections
        result = query_station_connections("MS01")
        station_ids = [r["to_station_id"] for r in result]
        assert station_ids == sorted(station_ids)


# ─────────────────────────────────────────────────────────────────────────────
#  query_shortest_route (Neo4j)
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryShortestRouteIntegration:
    """
    Integration tests for query_shortest_route (APOC Dijkstra).

    Station topology reference (from metro_stations.json / seed_neo4j.py):
      - MS01 (Central Square) directly connects to MS02, MS05, MS06, MS07 via CONNECTS_TO
        and to NR01 via INTERCHANGE
      - The shortest metro path MS01 → MS09 passes through 4 hops
        (station_ids: [MS01, MS03, MS06, MS08, MS09], per doc-16 example)
    """

    def test_shortest_route_metro_direct_connection(self):
        """MS01 and MS02 are directly connected — single hop must be found."""
        from databases.graph.queries import query_shortest_route
        result = query_shortest_route("MS01", "MS02")
        assert result["found"] is True
        assert result["total_travel_time_min"] > 0
        assert result["num_legs"] >= 1
        assert len(result["station_ids"]) == result["num_legs"] + 1

    def test_shortest_route_metro_multi_hop(self):
        """MS01 → MS09 is a multi-hop metro route."""
        from databases.graph.queries import query_shortest_route
        result = query_shortest_route("MS01", "MS09")
        assert result["found"] is True
        assert result["num_legs"] >= 2
        assert result["total_travel_time_min"] >= 4  # at least 4 min for 4 hops

    def test_shortest_route_station_ids_and_legs_structurally_consistent(self):
        """len(station_ids) == num_legs + 1 and len(legs) == num_legs."""
        from databases.graph.queries import query_shortest_route
        result = query_shortest_route("MS01", "MS09")
        assert result["found"] is True
        assert len(result["station_ids"]) == result["num_legs"] + 1
        assert len(result["legs"]) == result["num_legs"]

    def test_shortest_route_nonexistent_station_returns_found_false(self):
        """Invalid station ID must return found=False without raising an exception."""
        from databases.graph.queries import query_shortest_route
        result = query_shortest_route("MS01", "STATION_DOES_NOT_EXIST")
        assert result["found"] is False
        assert "error" in result

    def test_shortest_route_result_has_required_keys(self):
        """All documented return keys must be present."""
        from databases.graph.queries import query_shortest_route
        result = query_shortest_route("MS01", "MS09")
        required = {
            "found", "origin_id", "destination_id",
            "total_travel_time_min", "num_legs",
            "station_ids", "stations", "legs",
        }
        assert required.issubset(result.keys())


# ─────────────────────────────────────────────────────────────────────────────
#  query_alternative_routes (Neo4j)
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryAlternativeRoutesIntegration:
    """
    Integration tests for query_alternative_routes (allSimplePaths + node filter).

    MS03 is on the documented shortest path MS01→MS09
    (station_ids: [MS01, MS03, MS06, MS08, MS09]).
    Avoiding MS03 exercises the core filtering logic.
    """

    def test_alternative_routes_returns_list(self):
        """Function always returns a list — never raises an exception."""
        from databases.graph.queries import query_alternative_routes
        result = query_alternative_routes("MS01", "MS09", "MS03")
        assert isinstance(result, list)

    def test_alternative_routes_no_returned_route_contains_avoided_station(self):
        """Every returned route must exclude the avoided station_id."""
        from databases.graph.queries import query_alternative_routes
        result = query_alternative_routes("MS01", "MS09", "MS03")
        for route in result:
            assert "MS03" not in route["station_ids"], (
                f"avoided station MS03 found in route: {route['station_ids']}"
            )

    def test_alternative_routes_each_route_has_avoid_station_id_field(self):
        """Each returned route dict must carry the avoid_station_id field."""
        from databases.graph.queries import query_alternative_routes
        result = query_alternative_routes("MS01", "MS09", "MS03")
        for route in result:
            assert route.get("avoid_station_id") == "MS03"
            assert "station_ids" in route
            assert "legs" in route

    def test_alternative_routes_invalid_stations_returns_empty_list(self):
        """Completely invalid station IDs should silently return []."""
        from databases.graph.queries import query_alternative_routes
        result = query_alternative_routes("INVALID_A", "INVALID_B", "INVALID_C")
        assert result == []

    def test_alternative_routes_max_routes_respected(self):
        """Result length must not exceed the max_routes limit."""
        from databases.graph.queries import query_alternative_routes
        result = query_alternative_routes("MS01", "MS09", "MS10", max_routes=2)
        assert len(result) <= 2


# ─────────────────────────────────────────────────────────────────────────────
#  query_cheapest_route (Neo4j + cross-module fare lookup)
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryCheapestRouteIntegration:
    """
    Integration tests for query_cheapest_route.

    Uses NR01 → NR05 (national-rail same-network route) as the primary fixture
    because that route has concrete fare data in query_national_rail_fare.
    """

    def test_cheapest_route_national_rail_found(self):
        """NR01 → NR05 must produce at least one costed route."""
        from databases.graph.queries import query_cheapest_route
        result = query_cheapest_route("NR01", "NR05")
        assert result["found"] is True
        assert len(result["cheapest_routes"]) >= 1

    def test_cheapest_route_sorted_ascending_by_total_fare(self):
        """cheapest_routes list must be sorted from lowest to highest fare."""
        from databases.graph.queries import query_cheapest_route
        result = query_cheapest_route("NR01", "NR05")
        if result["found"] and len(result["cheapest_routes"]) > 1:
            fares = [r["total_fare_usd"] for r in result["cheapest_routes"]]
            assert fares == sorted(fares), (
                f"Routes are not sorted by fare: {fares}"
            )

    def test_cheapest_route_each_route_has_positive_fare_and_legs(self):
        """Each cheapest route must have total_fare_usd > 0 and a non-empty legs list."""
        from databases.graph.queries import query_cheapest_route
        result = query_cheapest_route("NR01", "NR05")
        if result["found"]:
            for route in result["cheapest_routes"]:
                assert route["total_fare_usd"] > 0
                assert "legs" in route
                assert len(route["legs"]) >= 1

    def test_cheapest_route_result_has_required_keys(self):
        """All documented top-level keys must be present in the response."""
        from databases.graph.queries import query_cheapest_route
        result = query_cheapest_route("NR01", "NR05")
        required = {"found", "origin_id", "destination_id", "cheapest_routes"}
        assert required.issubset(result.keys())

    def test_cheapest_route_invalid_station_returns_found_false(self):
        """Invalid destination must return found=False without raising."""
        from databases.graph.queries import query_cheapest_route
        result = query_cheapest_route("NR01", "INVALID_STATION")
        assert result["found"] is False
