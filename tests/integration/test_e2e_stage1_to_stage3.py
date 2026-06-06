"""
E2E Integration Test Suite — Stage 1 through Stage 3 (Full Pipeline)
=====================================================================
Validates the complete TransitFlow architecture end-to-end across all three stages.
Uses mock service objects injected via the SOLID DatabaseService interface to exercise
the full agent routing pipeline, fallback logic, cache, and exception layer without
requiring running database containers.

Test Scenarios
--------------
1. TestToolRoutingAccuracy        — Stage 1.3: agent dispatches every tool to the right DB call
2. TestCrossNetworkDataAggregation — Stage 1.2/1.3: PG relational + Neo4j graph fusion
3. TestSoldOutFallback            — Stage 2.1: sold-out fallback, cross-midnight MOD arithmetic
4. TestStage3ExcellenceLayer      — Stage 3.1/3.2/3.3/3.4: exception, cache, pool, logging
5. TestBookingCancellationWorkflow — Full transactional booking/cancellation lifecycle
"""

from __future__ import annotations

import json
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from skeleton.agent import TransitFlowAgent, _parse_tool_calls, error_handler
from skeleton.cache import CacheManager
from skeleton.exceptions import (
    DatabaseException,
    RouteNotFoundException,
    SeatUnavailableException,
    TransitFlowException,
    ValidationException,
)


# ── Shared mock factories ─────────────────────────────────────────────────────

def _make_mock_db():
    """Return a MagicMock implementing RelationalService with sane default data."""
    db = MagicMock()

    db.query_national_rail_availability.return_value = [
        {
            "schedule_id": "NR_SCH01",
            "line": "NR1",
            "direction": "northbound",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "first_train_time": "07:00",
            "last_train_time": "19:00",
            "base_fare_usd": 8.50,
            "travel_date": "2026-06-01",
            "total_seats": 18,
            "booked_seats": 5,
            "available_seats": 13,
        }
    ]
    db.query_national_rail_fare.return_value = {
        "schedule_id": "NR_SCH01",
        "fare_class": "standard",
        "total_fare_usd": 8.50,
        "currency": "USD",
    }
    db.query_metro_schedules.return_value = [
        {
            "schedule_id": "MS_SCH01",
            "line": "M1",
            "direction": "eastbound",
            "origin_station_id": "MS01",
            "destination_station_id": "MS09",
            "first_train_time": "06:00",
            "last_train_time": "23:00",
            "base_fare_usd": 2.50,
            "stops_in_order": ["MS01", "MS02", "MS03", "MS04", "MS09"],
        }
    ]
    db.query_metro_fare.return_value = {
        "schedule_id": "MS_SCH01",
        "stops_travelled": 4,
        "base_fare_usd": 0.80,
        "per_stop_rate_usd": 0.30,
        "total_fare_usd": 2.00,
    }
    db.query_available_seats.return_value = [
        {"seat_id": "A01", "coach": "A", "row": 1, "column": "A", "is_available": True},
        {"seat_id": "A02", "coach": "A", "row": 1, "column": "B", "is_available": True},
        {"seat_id": "B01", "coach": "B", "row": 1, "column": "A", "is_available": False},
    ]
    db.query_user_profile.return_value = {
        "user_id": "RU01",
        "full_name": "Alice Tan",
        "email": "alice.tan@email.com",
    }
    db.query_user_bookings.return_value = [
        {
            "booking_id": "BK-ALICE01",
            "schedule_id": "NR_SCH01",
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "travel_date": "2026-06-01",
            "status": "confirmed",
            "amount_usd": 8.50,
        }
    ]
    db.execute_booking.return_value = (True, {
        "booking_id": "BK-NEW001",
        "payment_id": "PM-NEW001",
        "user_id": "RU01",
        "schedule_id": "NR_SCH01",
        "origin_station_id": "NR01",
        "destination_station_id": "NR05",
        "travel_date": "2026-06-01",
        "fare_class": "standard",
        "seat_id": "A01",
        "total_fare_usd": 8.50,
        "status": "pending",
    })
    db.execute_cancellation.return_value = (True, {
        "booking_id": "BK-ALICE01",
        "original_amount_usd": 8.50,
        "status": "cancelled",
        "cancelled_at": "2026-05-21T10:00:00+00:00",
    })
    db.query_policy_vector_search.return_value = [
        {
            "title": "Refund Policy",
            "category": "refunds",
            "content": "Full refund if cancelled 24 hours before departure.",
            "similarity": 0.92,
        }
    ]
    return db


def _make_mock_graph():
    """Return a MagicMock implementing GraphService with sane default data."""
    graph = MagicMock()

    graph.query_shortest_route.return_value = {
        "found": True,
        "origin_id": "MS01",
        "destination_id": "MS09",
        "total_travel_time_min": 22,
        "num_legs": 4,
        "station_ids": ["MS01", "MS02", "MS03", "MS04", "MS09"],
        "stations": [
            {"station_id": "MS01", "name": "Central Square", "network_type": "metro"},
            {"station_id": "MS09", "name": "Queensbridge", "network_type": "metro"},
        ],
        "legs": [
            {
                "from_station_id": "MS01", "from_station_name": "Central Square",
                "to_station_id": "MS09", "to_station_name": "Queensbridge",
                "from_network": "metro", "to_network": "metro",
            }
        ],
    }
    graph.query_cheapest_route.return_value = {
        "found": True,
        "origin_id": "NR01",
        "destination_id": "NR05",
        "cheapest_routes": [
            {"station_ids": ["NR01", "NR02", "NR05"], "total_fare_usd": 8.50, "legs": []}
        ],
    }
    graph.query_interchange_path.return_value = {
        "found": True,
        "origin_id": "MS01",
        "destination_id": "NR05",
        "station_ids": ["MS01", "NR01", "NR02", "NR05"],
        "stations": [
            {"station_id": "MS01", "name": "Central Square", "network_type": "metro"},
            {"station_id": "NR01", "name": "Central Station", "network_type": "national_rail"},
            {"station_id": "NR05", "name": "Stonehaven", "network_type": "national_rail"},
        ],
        "interchange_points": [
            {
                "from_station_id": "MS01", "from_station_name": "Central Square",
                "from_network": "metro",
                "to_station_id": "NR01", "to_station_name": "Central Station",
                "to_network": "national_rail",
            }
        ],
        "total_travel_time_min": 35,
        "num_legs": 3,
        "legs": [
            {
                "from_station_id": "MS01", "to_station_id": "NR01",
                "relationship_type": "INTERCHANGE", "travel_time_min": 10,
                "from_network": "metro", "to_network": "national_rail",
            },
            {
                "from_station_id": "NR01", "to_station_id": "NR05",
                "relationship_type": "CONNECTS_TO", "travel_time_min": 25,
                "from_network": "national_rail", "to_network": "national_rail",
            },
        ],
    }
    graph.query_alternative_routes.return_value = [
        {
            "station_ids": ["NR01", "NR04", "NR05"],
            "stations": [],
            "legs": [],
            "avoid_station_id": "NR03",
        }
    ]
    graph.query_delay_ripple.return_value = {
        "affected_station_id": "NR03",
        "affected_station": {
            "station_id": "NR03", "name": "Old Town Junction",
            "network_type": "national_rail",
        },
        "primary_impact_zone": [
            {"station_id": "NR02", "name": "Maplewood",
             "network_type": "national_rail", "hops_away": 1},
            {"station_id": "NR04", "name": "Ashford",
             "network_type": "national_rail", "hops_away": 1},
        ],
        "secondary_impact_zone": [
            {"station_id": "NR01", "name": "Central Station",
             "network_type": "national_rail", "hops_away": 2},
        ],
        "total_affected_stations": 3,
        "total_hops_searched": 2,
    }
    return graph


def _make_conn_mock(fetchone_values=(), fetchall_value=()):
    """Build the standard psycopg2 connection/cursor mock chain."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    if fetchone_values:
        mock_cur.fetchone.side_effect = list(fetchone_values)
    if fetchall_value is not None:
        mock_cur.fetchall.return_value = list(fetchall_value)
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=None)
    mock_conn.cursor.return_value = mock_cur
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=None)
    return mock_conn, mock_cur


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — Agent Tool Routing Accuracy (Stage 1.3)
# Verifies that _execute_tool_inner routes each tool to exactly the right
# database call with correctly forwarded parameters.
# ═════════════════════════════════════════════════════════════════════════════

class TestToolRoutingAccuracy:

    def setup_method(self):
        self.db = _make_mock_db()
        self.graph = _make_mock_graph()
        self.agent = TransitFlowAgent(db_service=self.db, graph_service=self.graph)

    def test_national_rail_availability_routes_to_relational(self):
        result = self.agent._execute_tool_inner(
            "check_national_rail_availability",
            {"origin_id": "NR01", "destination_id": "NR05"},
        )
        self.db.query_national_rail_availability.assert_called_once_with(
            origin_id="NR01", destination_id="NR05"
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["schedule_id"] == "NR_SCH01"
        assert data[0]["available_seats"] == 13

    def test_national_rail_fare_routes_to_relational(self):
        result = self.agent._execute_tool_inner(
            "get_national_rail_fare",
            {"schedule_id": "NR_SCH01", "fare_class": "standard", "stops_travelled": 3},
        )
        self.db.query_national_rail_fare.assert_called_once_with(
            schedule_id="NR_SCH01", fare_class="standard", stops_travelled=3
        )
        data = json.loads(result)
        assert data["total_fare_usd"] == 8.50

    def test_metro_availability_routes_to_relational(self):
        result = self.agent._execute_tool_inner(
            "check_metro_availability",
            {"origin_id": "MS01", "destination_id": "MS09"},
        )
        self.db.query_metro_schedules.assert_called_once_with(
            origin_id="MS01", destination_id="MS09"
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["schedule_id"] == "MS_SCH01"

    def test_available_seats_routes_to_relational(self):
        result = self.agent._execute_tool_inner(
            "get_available_seats",
            {"schedule_id": "NR_SCH01", "travel_date": "2026-06-01", "fare_class": "first"},
        )
        self.db.query_available_seats.assert_called_once_with(
            schedule_id="NR_SCH01", travel_date="2026-06-01", fare_class="first"
        )
        data = json.loads(result)
        assert any(s["seat_id"] == "A01" for s in data)

    def test_search_policy_routes_to_vector_search(self):
        fake_embedding = [0.1] * 768
        with patch("skeleton.agent.llm") as mock_llm:
            mock_llm.embed.return_value = fake_embedding
            result = self.agent._execute_tool_inner(
                "search_policy",
                {"query": "refund policy for delays"},
            )
        self.db.query_policy_vector_search.assert_called_once_with(fake_embedding)
        data = json.loads(result)
        assert data[0]["title"] == "Refund Policy"
        assert data[0]["similarity"] == 0.92

    def test_find_route_time_optimised_uses_shortest(self):
        result = self.agent._execute_tool_inner(
            "find_route",
            {"origin_id": "MS01", "destination_id": "MS09", "optimise_by": "time"},
        )
        self.graph.query_shortest_route.assert_called_once_with(
            origin_id="MS01", destination_id="MS09", network="auto"
        )
        self.graph.query_interchange_path.assert_not_called()
        data = json.loads(result)
        assert data["found"] is True
        assert data["total_travel_time_min"] == 22

    def test_find_route_cost_optimised_uses_cheapest(self):
        result = self.agent._execute_tool_inner(
            "find_route",
            {"origin_id": "NR01", "destination_id": "NR05", "optimise_by": "cost"},
        )
        self.graph.query_cheapest_route.assert_called_once()
        self.graph.query_shortest_route.assert_not_called()
        data = json.loads(result)
        assert data["found"] is True

    def test_delay_ripple_routes_to_graph(self):
        result = self.agent._execute_tool_inner(
            "get_delay_ripple",
            {"station_id": "NR03", "hops": 2},
        )
        self.graph.query_delay_ripple.assert_called_once_with(
            delayed_station_id="NR03", hops=2
        )
        data = json.loads(result)
        assert data["total_affected_stations"] == 3
        assert len(data["primary_impact_zone"]) == 2

    def test_find_alternative_routes_dispatches_to_graph(self):
        result = self.agent._execute_tool_inner(
            "find_alternative_routes",
            {"origin_id": "NR01", "destination_id": "NR05", "avoid_station_id": "NR03"},
        )
        self.graph.query_alternative_routes.assert_called_once_with(
            origin_id="NR01",
            destination_id="NR05",
            avoid_station_id="NR03",
            network="auto",
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["route_number"] == 1

    def test_get_user_bookings_without_login_returns_error(self):
        result = self.agent._execute_tool_inner(
            "get_user_bookings", {}, current_user_email=None,
        )
        data = json.loads(result)
        assert "error" in data
        assert "logged in" in data["error"].lower()
        self.db.query_user_bookings.assert_not_called()

    def test_get_user_bookings_with_login_queries_relational(self):
        result = self.agent._execute_tool_inner(
            "get_user_bookings", {}, current_user_email="alice.tan@email.com",
        )
        self.db.query_user_bookings.assert_called_once_with("alice.tan@email.com")
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["booking_id"] == "BK-ALICE01"

    def test_make_booking_without_login_returns_error(self):
        result = self.agent._execute_tool_inner(
            "make_booking",
            {
                "schedule_id": "NR_SCH01", "origin_station_id": "NR01",
                "destination_station_id": "NR05", "travel_date": "2026-06-01",
                "fare_class": "standard", "seat_id": "A01",
            },
            current_user_email=None,
        )
        data = json.loads(result)
        assert "error" in data
        self.db.execute_booking.assert_not_called()

    def test_cancel_booking_without_login_returns_error(self):
        result = self.agent._execute_tool_inner(
            "cancel_booking",
            {"booking_id": "BK-ALICE01"},
            current_user_email=None,
        )
        data = json.loads(result)
        assert "error" in data
        self.db.execute_cancellation.assert_not_called()

    def test_unknown_tool_returns_error_dict(self):
        result = self.agent._execute_tool_inner("nonexistent_tool", {})
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — Cross-Network Data Aggregation (Stage 1.2 + 1.3)
# Verifies that PostgreSQL structured data and Neo4j graph topology are
# correctly queried and fused into normalised results.
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossNetworkDataAggregation:

    def setup_method(self):
        self.db = _make_mock_db()
        self.graph = _make_mock_graph()
        self.agent = TransitFlowAgent(db_service=self.db, graph_service=self.graph)

    def test_ms_to_nr_find_route_triggers_interchange_path(self):
        """MS01 (metro) → NR05 (rail): must route through interchange, not shortest."""
        result = self.agent._execute_tool_inner(
            "find_route", {"origin_id": "MS01", "destination_id": "NR05"},
        )
        self.graph.query_interchange_path.assert_called_once_with("MS01", "NR05")
        self.graph.query_shortest_route.assert_not_called()
        self.graph.query_cheapest_route.assert_not_called()

        data = json.loads(result)
        assert data["found"] is True
        assert len(data["interchange_points"]) == 1
        assert data["interchange_points"][0]["from_network"] == "metro"
        assert data["interchange_points"][0]["to_network"] == "national_rail"

    def test_nr_to_ms_find_route_also_triggers_interchange_path(self):
        """NR05 (rail) → MS01 (metro): reverse direction also uses interchange."""
        self.graph.query_interchange_path.return_value = {
            "found": True, "origin_id": "NR05", "destination_id": "MS01",
            "station_ids": ["NR05", "NR01", "MS01"], "stations": [],
            "interchange_points": [
                {"from_network": "national_rail", "to_network": "metro",
                 "from_station_id": "NR01", "to_station_id": "MS01"}
            ],
            "total_travel_time_min": 35, "num_legs": 2, "legs": [],
        }
        self.agent._execute_tool_inner(
            "find_route", {"origin_id": "NR05", "destination_id": "MS01"},
        )
        self.graph.query_interchange_path.assert_called_once_with("NR05", "MS01")

    def test_schedule_then_seat_pipeline_aggregates_correctly(self):
        """Two sequential tool calls simulate the schedule→seats agent pipeline."""
        sched_raw = self.agent._execute_tool_inner(
            "check_national_rail_availability",
            {"origin_id": "NR01", "destination_id": "NR05", "travel_date": "2026-06-01"},
        )
        schedules = json.loads(sched_raw)
        assert len(schedules) == 1
        schedule_id = schedules[0]["schedule_id"]

        seat_raw = self.agent._execute_tool_inner(
            "get_available_seats",
            {"schedule_id": schedule_id, "travel_date": "2026-06-01", "fare_class": "first"},
        )
        seats = json.loads(seat_raw)
        available = [s for s in seats if s["is_available"]]
        assert len(available) == 2
        assert available[0]["seat_id"] == "A01"

    def test_interchange_path_plus_rail_schedule_combined(self):
        """Cross-network: graph path then PG schedule info — both succeed together."""
        route_raw = self.agent._execute_tool_inner(
            "find_route", {"origin_id": "MS01", "destination_id": "NR05"},
        )
        route = json.loads(route_raw)
        assert route["found"] is True
        assert route["total_travel_time_min"] == 35

        # After getting interchange at NR01, query rail leg availability
        sched_raw = self.agent._execute_tool_inner(
            "check_national_rail_availability",
            {"origin_id": "NR01", "destination_id": "NR05"},
        )
        sched = json.loads(sched_raw)
        assert len(sched) > 0
        assert sched[0]["available_seats"] == 13

    def test_delay_ripple_propagates_across_connected_stations(self):
        """Delay at NR03 propagates to primary (1-hop) and secondary (2-hop) zones."""
        result_raw = self.agent._execute_tool_inner(
            "get_delay_ripple", {"station_id": "NR03"},
        )
        data = json.loads(result_raw)
        assert data["total_affected_stations"] == 3
        primary_ids = [s["station_id"] for s in data["primary_impact_zone"]]
        assert "NR02" in primary_ids
        assert "NR04" in primary_ids
        secondary_ids = [s["station_id"] for s in data["secondary_impact_zone"]]
        assert "NR01" in secondary_ids

    def test_policy_vector_search_fuses_embedding_with_document_content(self):
        """RAG: llm.embed produces a vector, DB returns semantically matched docs."""
        fake_embedding = [0.5] * 768
        with patch("skeleton.agent.llm") as mock_llm:
            mock_llm.embed.return_value = fake_embedding
            result_raw = self.agent._execute_tool_inner(
                "search_policy",
                {"query": "what is the refund for a delayed train?"},
            )
        data = json.loads(result_raw)
        assert len(data) == 1
        assert data[0]["similarity"] > 0.5
        assert "refund" in data[0]["content"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — Sold-Out & Cross-Midnight Fallback (Stage 2.1)
# Tests the fallback schedule search with MOD arithmetic, date-range
# validation, interchange feasibility, and round-trip date ordering.
# ═════════════════════════════════════════════════════════════════════════════

class TestSoldOutFallback:

    def test_fallback_finds_alternatives_on_same_route(self):
        """query_alternative_schedules_fallback returns alternatives within 3 hours."""
        from databases.relational.queries import query_alternative_schedules_fallback

        original_row = {
            "origin_station_id": "NR01",
            "destination_station_id": "NR05",
            "first_train_time": "07:00:00",
        }
        alt_row = {
            "schedule_id": "NR_SCH02", "line": "NR1", "direction": "northbound",
            "service_type": "normal",
            "origin_station_id": "NR01", "destination_station_id": "NR05",
            "departure_time": "08:30", "base_fare_usd": 8.50,
            "travel_date": "2026-06-01", "total_seats": 18,
            "booked_seats": 3, "available_seats": 15, "time_diff_seconds": 5400,
        }

        mock_conn, mock_cur = _make_conn_mock(
            fetchone_values=[original_row],
            fetchall_value=[alt_row],
        )
        with patch("databases.relational.queries._connect", return_value=mock_conn):
            result = query_alternative_schedules_fallback("NR_SCH01", "2026-06-01")

        assert result["error"] is None
        assert result["alternatives_found"] == 1
        assert result["alternatives"][0]["schedule_id"] == "NR_SCH02"
        assert result["alternatives"][0]["available_seats"] == 15
        assert result["original_departure_time"] == "07:00"

    def test_fallback_returns_schedule_not_found_for_invalid_id(self):
        """SCHEDULE_NOT_FOUND returned when schedule_id does not exist."""
        from databases.relational.queries import query_alternative_schedules_fallback

        mock_conn, mock_cur = _make_conn_mock(fetchone_values=[None])
        with patch("databases.relational.queries._connect", return_value=mock_conn):
            result = query_alternative_schedules_fallback("NR_INVALID", "2026-06-01")

        assert result["error"] == "SCHEDULE_NOT_FOUND"
        assert result["alternatives_found"] == 0

    def test_fallback_returns_no_alternatives_when_all_trains_full(self):
        """NO_ALTERNATIVES_FOUND when all trains within 3 hours are also sold out."""
        from databases.relational.queries import query_alternative_schedules_fallback

        original_row = {
            "origin_station_id": "NR01", "destination_station_id": "NR05",
            "first_train_time": "23:30:00",  # Cross-midnight edge case
        }
        mock_conn, mock_cur = _make_conn_mock(
            fetchone_values=[original_row], fetchall_value=[],
        )
        with patch("databases.relational.queries._connect", return_value=mock_conn):
            result = query_alternative_schedules_fallback("NR_SCH_NIGHT", "2026-06-01")

        assert result["error"] == "NO_ALTERNATIVES_FOUND"
        assert result["alternatives"] == []

    def test_date_range_query_rejects_invalid_format(self):
        from databases.relational.queries import query_schedules_by_date_range
        result = query_schedules_by_date_range("NR01", "NR05", "not-a-date", "2026-06-10")
        assert result["error"] == "INVALID_DATE_FORMAT"

    def test_date_range_query_rejects_inverted_range(self):
        from databases.relational.queries import query_schedules_by_date_range
        result = query_schedules_by_date_range("NR01", "NR05", "2026-06-15", "2026-06-01")
        assert result["error"] == "INVALID_DATE_RANGE"

    def test_date_range_query_rejects_range_exceeding_14_days(self):
        from databases.relational.queries import query_schedules_by_date_range
        result = query_schedules_by_date_range("NR01", "NR05", "2026-06-01", "2026-07-01")
        assert result["error"] == "DATE_RANGE_EXCEEDS_14_DAYS"

    def test_date_range_query_accepts_valid_14_day_window(self):
        """Exactly 14-day range (13-day gap) must be accepted."""
        from databases.relational.queries import query_schedules_by_date_range

        mock_conn, mock_cur = _make_conn_mock(fetchall_value=[])
        with patch("databases.relational.queries._connect", return_value=mock_conn):
            result = query_schedules_by_date_range("NR01", "NR05", "2026-06-01", "2026-06-14")

        assert result["error"] is None
        assert result["origin_id"] == "NR01"
        assert result["total_found"] == 0

    def test_interchange_feasibility_accepts_15_min_transfer(self):
        from databases.graph.queries import validate_interchange_feasibility
        path = {
            "legs": [
                {"relationship_type": "CONNECTS_TO", "travel_time_min": 8},
                {"relationship_type": "INTERCHANGE", "travel_time_min": 15},
                {"relationship_type": "CONNECTS_TO", "travel_time_min": 12},
            ]
        }
        assert validate_interchange_feasibility(path) is True

    def test_interchange_feasibility_rejects_5_min_transfer(self):
        from databases.graph.queries import validate_interchange_feasibility
        path = {
            "legs": [
                {"relationship_type": "CONNECTS_TO", "travel_time_min": 8},
                {"relationship_type": "INTERCHANGE", "travel_time_min": 5},
            ]
        }
        assert validate_interchange_feasibility(path) is False

    def test_interchange_feasibility_accepts_same_network_path(self):
        """Paths with no INTERCHANGE legs are always feasible."""
        from databases.graph.queries import validate_interchange_feasibility
        path = {
            "legs": [
                {"relationship_type": "CONNECTS_TO", "travel_time_min": 10},
                {"relationship_type": "CONNECTS_TO", "travel_time_min": 8},
            ]
        }
        assert validate_interchange_feasibility(path) is True

    def test_interchange_feasibility_layout_b_timestamp_based(self):
        """Layout B: interchange_points with arrival/departure timestamps."""
        from databases.graph.queries import validate_interchange_feasibility
        path = {
            "interchange_points": [
                {"arrival_time": "10:00", "departure_time": "10:20"}  # 20 min — ok
            ]
        }
        assert validate_interchange_feasibility(path) is True

    def test_interchange_feasibility_layout_b_rejects_short_transfer(self):
        from databases.graph.queries import validate_interchange_feasibility
        path = {
            "interchange_points": [
                {"arrival_time": "10:00", "departure_time": "10:05"}  # 5 min — too short
            ]
        }
        assert validate_interchange_feasibility(path) is False

    def test_round_trip_itinerary_rejects_return_before_outbound(self):
        """query_round_trip_itinerary raises ValidationException for inverted dates."""
        from databases.relational.queries import query_round_trip_itinerary
        with pytest.raises(ValidationException) as exc_info:
            query_round_trip_itinerary(
                origin_id="NR01", destination_id="NR05",
                outbound_date="2026-06-10", return_date="2026-06-01",
            )
        assert "INVALID_DATE_ORDER" in exc_info.value.error_code

    def test_round_trip_itinerary_rejects_invalid_date_format(self):
        from databases.relational.queries import query_round_trip_itinerary
        with pytest.raises(ValidationException) as exc_info:
            query_round_trip_itinerary(
                origin_id="NR01", destination_id="NR05",
                outbound_date="not-a-date", return_date="2026-06-10",
            )
        assert "INVALID_DATE_FORMAT" in exc_info.value.error_code


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 4 — Stage 3 Excellence Layer
# Tests the full Stage 3 stack: exception hierarchy, error_handler decorator,
# SOLID service injection, LRU+TTL cache, connection pool, and structured logging.
# ═════════════════════════════════════════════════════════════════════════════

class TestStage3ExcellenceLayer:

    # ── 3.1 Exception Hierarchy ───────────────────────────────────────────────

    def test_transitflow_exception_carries_message_and_code(self):
        exc = TransitFlowException("something broke", "BROKE_001")
        assert exc.message == "something broke"
        assert exc.error_code == "BROKE_001"
        assert str(exc) == "something broke"

    def test_database_exception_is_transitflow_exception(self):
        exc = DatabaseException("db down", "DB_DOWN")
        assert isinstance(exc, TransitFlowException)
        assert exc.error_code == "DB_DOWN"

    def test_validation_exception_is_transitflow_exception(self):
        assert isinstance(ValidationException("bad", "BAD"), TransitFlowException)

    def test_route_not_found_exception_is_transitflow_exception(self):
        assert isinstance(RouteNotFoundException("no path", "NO_PATH"), TransitFlowException)

    def test_seat_unavailable_exception_is_transitflow_exception(self):
        assert isinstance(SeatUnavailableException("taken", "SEAT"), TransitFlowException)

    def test_error_handler_converts_transitflow_exception_to_uniform_json(self):
        @error_handler
        def failing_tool():
            raise TransitFlowException("route not found", "ROUTE_ERR")

        result = json.loads(failing_tool())
        assert result["success"] is False
        assert result["error"]["message"] == "route not found"
        assert result["error"]["code"] == "ROUTE_ERR"

    def test_error_handler_converts_generic_exception_to_internal_error(self):
        @error_handler
        def crashing_tool():
            raise RuntimeError("unexpected crash")

        result = json.loads(crashing_tool())
        assert result["success"] is False
        assert result["error"]["code"] == "INTERNAL_ERROR"

    def test_error_handler_passes_through_successful_return_unchanged(self):
        @error_handler
        def good_tool():
            return json.dumps({"schedule_id": "NR_SCH01"})

        result = json.loads(good_tool())
        assert result["schedule_id"] == "NR_SCH01"

    def test_execute_tool_returns_uniform_error_on_database_exception(self):
        """_execute_tool (with decorator) wraps DatabaseException as uniform JSON."""
        db = _make_mock_db()
        db.query_national_rail_availability.side_effect = DatabaseException(
            "connection refused", "DB_CONN_FAILED"
        )
        agent = TransitFlowAgent(db_service=db, graph_service=_make_mock_graph())

        raw = agent._execute_tool(
            "check_national_rail_availability",
            {"origin_id": "NR01", "destination_id": "NR05"},
        )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "DB_CONN_FAILED"

    # ── 3.2 SOLID Service Injection ───────────────────────────────────────────

    def test_agent_accepts_any_object_implementing_service_interface(self):
        """TransitFlowAgent works with any duck-typed service — not just psycopg2."""
        class MinimalRelational:
            def query_national_rail_availability(self, **kw): return []
            def query_national_rail_fare(self, **kw): return None
            def query_metro_schedules(self, **kw): return []
            def query_metro_fare(self, **kw): return {}
            def query_available_seats(self, **kw): return []
            def auto_select_adjacent_seats(self, **kw): return []
            def query_user_profile(self, *a, **kw): return None
            def query_user_bookings(self, *a, **kw): return []
            def execute_booking(self, **kw): return (False, "stub")
            def execute_cancellation(self, **kw): return (False, "stub")
            def query_policy_vector_search(self, *a, **kw): return []

        class MinimalGraph:
            def query_shortest_route(self, **kw): return {"found": False}
            def query_cheapest_route(self, **kw): return {"found": False}
            def query_alternative_routes(self, **kw): return []
            def query_interchange_path(self, *a, **kw): return {"found": False}
            def query_delay_ripple(self, **kw): return {}

        agent = TransitFlowAgent(
            db_service=MinimalRelational(),
            graph_service=MinimalGraph(),
        )
        raw = agent._execute_tool_inner(
            "check_national_rail_availability",
            {"origin_id": "NR01", "destination_id": "NR05"},
        )
        assert json.loads(raw) == []

    # ── 3.3 LRU + TTL Cache ───────────────────────────────────────────────────

    def test_cache_miss_then_hit_increments_counters(self):
        cache = CacheManager(max_size=10, ttl_seconds=60)
        assert cache.get("k1") is None          # MISS
        cache.set("k1", {"value": 42})
        assert cache.get("k1") == {"value": 42}  # HIT
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cache_ttl_expiry_removes_entry(self):
        cache = CacheManager(max_size=10, ttl_seconds=1)
        cache.set("expire_me", "stale")
        assert cache.get("expire_me") == "stale"
        time.sleep(1.1)
        assert cache.get("expire_me") is None  # Expired

    def test_cache_lru_evicts_least_recently_used_on_overflow(self):
        cache = CacheManager(max_size=3, ttl_seconds=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.get("a")           # Re-access 'a' → 'b' becomes LRU
        cache.set("d", 4)        # Should evict 'b'
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_cache_clear_resets_all_state(self):
        cache = CacheManager(max_size=10, ttl_seconds=300)
        cache.set("x", "val")
        cache.get("x")
        cache.clear()
        s = cache.stats()
        assert s["size"] == 0
        assert s["hits"] == 0
        assert s["misses"] == 0

    def test_cache_thread_safety_under_concurrent_reads_writes(self):
        cache = CacheManager(max_size=100, ttl_seconds=300)
        errors: list[Exception] = []

        def writer(n: int):
            try:
                for i in range(20):
                    cache.set(f"key_{n}_{i}", f"val_{n}_{i}")
            except Exception as e:
                errors.append(e)

        def reader(n: int):
            try:
                for i in range(20):
                    cache.get(f"key_{n}_{i}")
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=writer, args=(t,)) for t in range(5)] +
            [threading.Thread(target=reader, args=(t,)) for t in range(5)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety violations: {errors}"

    def test_fare_cache_stores_result_and_prevents_second_db_call(self):
        """query_national_rail_fare caches on first call; second call is cache-only."""
        from skeleton.cache import fare_cache
        from databases.relational.queries import query_national_rail_fare

        fare_cache.clear()
        cache_key = "fare:NR01:NR05:standard"
        assert fare_cache.get(cache_key) is None

        mock_conn, mock_cur = _make_conn_mock(
            fetchone_values=[{"base_fare_usd": 8.50, "per_stop_rate_usd": 0.0}],
        )
        with patch("databases.relational.queries._connect", return_value=mock_conn) as mc:
            query_national_rail_fare("NR01", "NR05", "standard")
            assert mc.call_count == 1
            query_national_rail_fare("NR01", "NR05", "standard")
            assert mc.call_count == 1  # Second call served from cache

        cached = fare_cache.get(cache_key)
        assert cached is not None
        assert cached["total_fare_usd"] == 8.50
        fare_cache.clear()

    # ── 3.4 Structured Logging ────────────────────────────────────────────────

    def test_structured_logger_emits_valid_json_with_required_fields(self, capsys):
        """StructuredLogger emits a JSON line containing timestamp, event, and extras."""
        import logging
        from skeleton.logging_config import StructuredLogger

        logger = StructuredLogger("test.e2e.structured", level=logging.DEBUG)
        logger.info("test_event", tool="find_route", duration_ms=42.5)

        captured = capsys.readouterr()
        output = captured.out + captured.err
        log_line = None
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
                if parsed.get("event") == "test_event":
                    log_line = parsed
                    break
            except json.JSONDecodeError:
                continue

        assert log_line is not None, "No JSON log line found in captured output"
        assert log_line["event"] == "test_event"
        assert log_line["tool"] == "find_route"
        assert log_line["duration_ms"] == 42.5
        assert "timestamp" in log_line

    # ── 3.3 Connection Pool ───────────────────────────────────────────────────

    def test_neo4j_pool_context_manager_does_not_close_driver(self):
        """Pool __exit__ must NOT close the driver — the singleton must stay alive."""
        from databases.graph.connection_pool import Neo4jConnectionPool

        with patch("databases.graph.connection_pool.GraphDatabase.driver") as mock_drv:
            mock_drv.return_value = MagicMock()
            pool = Neo4jConnectionPool("bolt://localhost:7688", "neo4j", "test")
            with pool:
                pass  # __exit__ called here
            mock_drv.return_value.close.assert_not_called()

    def test_neo4j_pool_singleton_initialized_only_once(self):
        """get_pool() must return the same object on repeated calls (singleton)."""
        from databases.graph import connection_pool

        original = connection_pool._pool
        try:
            with patch("databases.graph.connection_pool.GraphDatabase.driver") as mock_drv:
                mock_drv.return_value = MagicMock()
                connection_pool._pool = None
                pool1 = connection_pool.get_pool()
                pool2 = connection_pool.get_pool()
                assert pool1 is pool2
                assert mock_drv.call_count == 1
        finally:
            connection_pool._pool = original


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 5 — Booking & Cancellation Full Lifecycle + Tool-Call Parsing
# ═════════════════════════════════════════════════════════════════════════════

class TestBookingCancellationWorkflow:

    def setup_method(self):
        self.db = _make_mock_db()
        self.graph = _make_mock_graph()
        self.agent = TransitFlowAgent(db_service=self.db, graph_service=self.graph)

    def test_make_booking_resolves_profile_then_calls_execute(self):
        """make_booking: agent looks up profile by email, passes user_id to execute."""
        raw = self.agent._execute_tool_inner(
            "make_booking",
            {
                "schedule_id": "NR_SCH01", "origin_station_id": "NR01",
                "destination_station_id": "NR05", "travel_date": "2026-06-01",
                "fare_class": "standard", "seat_id": "A01", "ticket_type": "single",
            },
            current_user_email="alice.tan@email.com",
        )
        self.db.query_user_profile.assert_called_once_with("alice.tan@email.com")
        self.db.execute_booking.assert_called_once()
        kw = self.db.execute_booking.call_args[1]
        assert kw["user_id"] == "RU01"
        assert kw["schedule_id"] == "NR_SCH01"

        data = json.loads(raw)
        assert data["booking_id"] == "BK-NEW001"
        assert data["status"] == "pending"

    def test_cancel_booking_resolves_profile_then_calls_execute(self):
        """cancel_booking: agent looks up profile, then calls execute_cancellation."""
        raw = self.agent._execute_tool_inner(
            "cancel_booking",
            {"booking_id": "BK-ALICE01"},
            current_user_email="alice.tan@email.com",
        )
        self.db.query_user_profile.assert_called_once_with("alice.tan@email.com")
        self.db.execute_cancellation.assert_called_once_with(
            booking_id="BK-ALICE01", user_id="RU01",
        )
        data = json.loads(raw)
        assert data["status"] == "cancelled"

    def test_make_booking_returns_error_when_profile_not_found(self):
        """If profile lookup returns None, booking must be rejected cleanly."""
        self.db.query_user_profile.return_value = None
        raw = self.agent._execute_tool_inner(
            "make_booking",
            {
                "schedule_id": "NR_SCH01", "origin_station_id": "NR01",
                "destination_station_id": "NR05", "travel_date": "2026-06-01",
                "fare_class": "standard", "seat_id": "A01",
            },
            current_user_email="ghost@email.com",
        )
        data = json.loads(raw)
        assert "error" in data
        self.db.execute_booking.assert_not_called()

    def test_booking_failure_propagates_error_message(self):
        """If execute_booking returns (False, msg), agent wraps it as error dict."""
        self.db.execute_booking.return_value = (False, "Seat A01 already booked")
        raw = self.agent._execute_tool_inner(
            "make_booking",
            {
                "schedule_id": "NR_SCH01", "origin_station_id": "NR01",
                "destination_station_id": "NR05", "travel_date": "2026-06-01",
                "fare_class": "standard", "seat_id": "A01",
            },
            current_user_email="alice.tan@email.com",
        )
        data = json.loads(raw)
        assert data.get("error") == "Seat A01 already booked"

    def test_parse_tool_calls_extracts_bare_json(self):
        bare = ('{"tool_calls": [{"name": "find_route", '
                '"params": {"origin_id": "MS01", "destination_id": "MS09"}}]}')
        parsed = _parse_tool_calls(bare)
        assert parsed is not None
        assert parsed[0]["name"] == "find_route"
        assert parsed[0]["params"]["origin_id"] == "MS01"

    def test_parse_tool_calls_strips_markdown_fences(self):
        fenced = ('```json\n{"tool_calls": [{"name": "search_policy", '
                  '"params": {"query": "refund"}}]}\n```')
        parsed = _parse_tool_calls(fenced)
        assert parsed is not None
        assert parsed[0]["name"] == "search_policy"

    def test_parse_tool_calls_returns_empty_list_for_no_tool_response(self):
        parsed = _parse_tool_calls('{"tool_calls": []}')
        assert parsed == []

    def test_parse_tool_calls_returns_none_for_non_json_text(self):
        result = _parse_tool_calls("I'm sorry, I cannot help with that.")
        assert result is None
