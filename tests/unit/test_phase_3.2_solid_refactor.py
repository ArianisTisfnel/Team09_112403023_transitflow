"""
Unit tests for Stage 3.2 — SOLID Database Service Layer (Dependency Injection)

DoD coverage:
  1. DatabaseService / RelationalService / GraphService ABC hierarchy is correct
  2. PostgreSQLService and Neo4jService are both concrete subclasses of DatabaseService
  3. PostgreSQLService / Neo4jService store dsn/uri and delegate calls to query modules
  4. TransitFlowAgent.__init__ accepts db_service + graph_service (DI)
  5. TransitFlowAgent._execute_tool routes through self.db.* and self.graph.*
     — confirmed by injecting mock services and asserting the mock was called
  6. Agent source has no direct psycopg2 / neo4j driver references (no coupling)
  7. Module-level run_agent delegates to _default_agent.run()
  8. error_handler remains active on TransitFlowAgent._execute_tool after refactoring
"""

import inspect
import json
import re
import sys
from abc import ABC
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy dependencies before any skeleton import ────────────────────────
# LLMProvider tries to connect to Ollama on import; DB modules need live servers.
# Use setdefault so the stub only wins if the real module isn't loaded yet.
sys.modules.setdefault("skeleton.llm_provider", MagicMock(llm=MagicMock()))
sys.modules.setdefault("databases.relational.queries", MagicMock())
sys.modules.setdefault("databases.graph.queries", MagicMock())

import skeleton.agent as _agent_module
from skeleton.database_service import (
    DatabaseService,
    GraphService,
    Neo4jService,
    PostgreSQLService,
    RelationalService,
)
from skeleton.agent import TransitFlowAgent, _default_agent, run_agent
from skeleton.exceptions import (
    DatabaseException,
    RouteNotFoundException,
    SeatUnavailableException,
)


# ═════════════════════════════════════════════════════════════════════════════
# 1. ABC hierarchy — skeleton/database_service.py
# ═════════════════════════════════════════════════════════════════════════════

class TestDatabaseServiceHierarchy:
    """Validates the full abstract class chain defined in database_service.py."""

    def test_database_service_is_abc_subclass(self):
        """DatabaseService must extend ABC (marker base for all services)."""
        assert issubclass(DatabaseService, ABC)

    def test_relational_service_is_abstract(self):
        """RelationalService has abstract methods — cannot be instantiated."""
        with pytest.raises(TypeError):
            RelationalService()

    def test_graph_service_is_abstract(self):
        """GraphService has abstract methods — cannot be instantiated."""
        with pytest.raises(TypeError):
            GraphService()

    def test_relational_service_inherits_database_service(self):
        assert issubclass(RelationalService, DatabaseService)

    def test_graph_service_inherits_database_service(self):
        assert issubclass(GraphService, DatabaseService)

    def test_postgresql_service_inherits_relational_service(self):
        assert issubclass(PostgreSQLService, RelationalService)

    def test_neo4j_service_inherits_graph_service(self):
        assert issubclass(Neo4jService, GraphService)

    def test_postgresql_service_is_database_service_subclass(self):
        """DoD: PostgreSQLService must (transitively) inherit from DatabaseService."""
        assert issubclass(PostgreSQLService, DatabaseService)

    def test_neo4j_service_is_database_service_subclass(self):
        """DoD: Neo4jService must (transitively) inherit from DatabaseService."""
        assert issubclass(Neo4jService, DatabaseService)

    def test_at_least_two_concrete_database_service_subclasses(self):
        """DoD: at least 2 concrete classes inheriting from DatabaseService."""
        concrete = [cls for cls in (PostgreSQLService, Neo4jService)
                    if issubclass(cls, DatabaseService)]
        assert len(concrete) >= 2

    def test_postgresql_service_is_instantiable(self):
        """PostgreSQLService is concrete — must not raise TypeError on init."""
        svc = PostgreSQLService(dsn="postgresql://user:pass@localhost/db")
        assert svc is not None

    def test_neo4j_service_is_instantiable(self):
        """Neo4jService is concrete — must not raise TypeError on init."""
        svc = Neo4jService(uri="bolt://localhost:7687")
        assert svc is not None


# ═════════════════════════════════════════════════════════════════════════════
# 2. PostgreSQLService — dsn storage and method delegation
# ═════════════════════════════════════════════════════════════════════════════

class TestPostgreSQLService:
    """PostgreSQLService must store the DSN and delegate every method to self._q."""

    @pytest.fixture
    def svc(self):
        svc = PostgreSQLService(dsn="postgresql://test:test@localhost/test")
        svc._q = MagicMock()  # guarantee _q is a mock regardless of import order
        return svc

    def test_stores_dsn(self, svc):
        assert svc.dsn == "postgresql://test:test@localhost/test"

    def test_query_national_rail_availability_delegates(self, svc):
        svc._q.query_national_rail_availability.return_value = [{"id": "NR_SCH01"}]
        result = svc.query_national_rail_availability("NR01", "NR05")
        svc._q.query_national_rail_availability.assert_called_once_with("NR01", "NR05", None)
        assert result == [{"id": "NR_SCH01"}]

    def test_query_national_rail_fare_delegates(self, svc):
        svc._q.query_national_rail_fare.return_value = {"fare": 12.5}
        result = svc.query_national_rail_fare("NR_SCH01", "standard", 3)
        svc._q.query_national_rail_fare.assert_called_once_with("NR_SCH01", "standard", 3)
        assert result == {"fare": 12.5}

    def test_query_metro_schedules_delegates(self, svc):
        svc._q.query_metro_schedules.return_value = []
        svc.query_metro_schedules("MS01", "MS09")
        svc._q.query_metro_schedules.assert_called_once_with("MS01", "MS09")

    def test_query_metro_fare_delegates(self, svc):
        svc._q.query_metro_fare.return_value = {"total_fare_usd": 2.5}
        svc.query_metro_fare("MS_SCH01", 4)
        svc._q.query_metro_fare.assert_called_once_with("MS_SCH01", 4)

    def test_query_user_profile_delegates(self, svc):
        svc._q.query_user_profile.return_value = {"user_id": "U001"}
        result = svc.query_user_profile("user@example.com")
        svc._q.query_user_profile.assert_called_once_with("user@example.com")
        assert result == {"user_id": "U001"}

    def test_execute_booking_delegates(self, svc):
        svc._q.execute_booking.return_value = (True, {"booking_id": "BK-ABCD12"})
        result = svc.execute_booking("U001", "NR_SCH01", "NR01", "NR05",
                                     "2026-06-01", "standard", "A01", "single")
        svc._q.execute_booking.assert_called_once()
        assert result[0] is True

    def test_execute_cancellation_delegates(self, svc):
        svc._q.execute_cancellation.return_value = (True, {"refund": 10.0})
        result = svc.execute_cancellation("BK-ABCD12", "U001")
        svc._q.execute_cancellation.assert_called_once_with("BK-ABCD12", "U001")
        assert result[0] is True

    def test_query_policy_vector_search_delegates(self, svc):
        embedding = [0.1] * 768
        svc._q.query_policy_vector_search.return_value = []
        svc.query_policy_vector_search(embedding)
        svc._q.query_policy_vector_search.assert_called_once_with(embedding)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Neo4jService — uri storage and method delegation
# ═════════════════════════════════════════════════════════════════════════════

class TestNeo4jService:
    """Neo4jService must store the URI and delegate every method to self._q."""

    @pytest.fixture
    def svc(self):
        svc = Neo4jService(uri="bolt://localhost:7687")
        svc._q = MagicMock()  # guarantee _q is a mock regardless of import order
        return svc

    def test_stores_uri(self, svc):
        assert svc.uri == "bolt://localhost:7687"

    def test_query_shortest_route_delegates(self, svc):
        svc._q.query_shortest_route.return_value = {"path": ["NR01", "NR05"]}
        result = svc.query_shortest_route("NR01", "NR05")
        svc._q.query_shortest_route.assert_called_once_with("NR01", "NR05", "auto")
        assert result == {"path": ["NR01", "NR05"]}

    def test_query_cheapest_route_delegates(self, svc):
        svc._q.query_cheapest_route.return_value = {"path": ["NR01", "NR02", "NR05"]}
        svc.query_cheapest_route("NR01", "NR05")
        svc._q.query_cheapest_route.assert_called_once_with("NR01", "NR05", "auto")

    def test_query_alternative_routes_delegates(self, svc):
        svc._q.query_alternative_routes.return_value = []
        svc.query_alternative_routes("NR01", "NR05", "NR03")
        svc._q.query_alternative_routes.assert_called_once_with("NR01", "NR05", "NR03", "auto")

    def test_query_interchange_path_delegates(self, svc):
        svc._q.query_interchange_path.return_value = {"legs": []}
        svc.query_interchange_path("MS01", "NR01")
        svc._q.query_interchange_path.assert_called_once_with("MS01", "NR01")

    def test_query_delay_ripple_delegates(self, svc):
        svc._q.query_delay_ripple.return_value = []
        svc.query_delay_ripple("NR03")
        svc._q.query_delay_ripple.assert_called_once_with("NR03", 2)

    def test_query_delay_ripple_custom_hops(self, svc):
        svc.query_delay_ripple("MS07", hops=3)
        # assert_called_with checks the most recent call (shared MagicMock may
        # accumulate calls across tests in the same session).
        svc._q.query_delay_ripple.assert_called_with("MS07", 3)


# ═════════════════════════════════════════════════════════════════════════════
# 4. TransitFlowAgent — dependency injection
# ═════════════════════════════════════════════════════════════════════════════

class TestTransitFlowAgentDI:
    """TransitFlowAgent.__init__ must store injected services without touching drivers."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=RelationalService)

    @pytest.fixture
    def mock_graph(self):
        return MagicMock(spec=GraphService)

    @pytest.fixture
    def agent(self, mock_db, mock_graph):
        return TransitFlowAgent(db_service=mock_db, graph_service=mock_graph)

    def test_stores_db_service(self, agent, mock_db):
        assert agent.db is mock_db

    def test_stores_graph_service(self, agent, mock_graph):
        assert agent.graph is mock_graph

    def test_accepts_any_relational_service_implementation(self):
        """DI principle: any RelationalService subclass is accepted."""
        class AltDB(RelationalService):
            def query_national_rail_availability(self, *a, **kw): pass
            def query_national_rail_fare(self, *a, **kw): pass
            def query_metro_schedules(self, *a, **kw): pass
            def query_metro_fare(self, *a, **kw): pass
            def query_available_seats(self, *a, **kw): pass
            def auto_select_adjacent_seats(self, *a, **kw): pass
            def query_user_profile(self, *a, **kw): pass
            def query_user_bookings(self, *a, **kw): pass
            def execute_booking(self, *a, **kw): pass
            def execute_cancellation(self, *a, **kw): pass
            def query_policy_vector_search(self, *a, **kw): pass

        alt = AltDB()
        a = TransitFlowAgent(db_service=alt, graph_service=MagicMock(spec=GraphService))
        assert a.db is alt

    def test_accepts_any_graph_service_implementation(self):
        """DI principle: any GraphService subclass is accepted."""
        class AltGraph(GraphService):
            def query_shortest_route(self, *a, **kw): pass
            def query_cheapest_route(self, *a, **kw): pass
            def query_alternative_routes(self, *a, **kw): pass
            def query_interchange_path(self, *a, **kw): pass
            def query_delay_ripple(self, *a, **kw): pass

        alt = AltGraph()
        a = TransitFlowAgent(db_service=MagicMock(spec=RelationalService), graph_service=alt)
        assert a.graph is alt

    def test_execute_tool_has_wrapped_attribute(self, agent):
        """@error_handler must still be active after Stage 3.2 refactoring."""
        assert hasattr(agent._execute_tool, "__wrapped__"), (
            "TransitFlowAgent._execute_tool lacks __wrapped__; "
            "@error_handler may not be applied"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 5. _execute_tool dispatches through injected services
# ═════════════════════════════════════════════════════════════════════════════

class TestExecuteToolUsesInjectedServices:
    """
    DoD: Agent must not call psycopg2/neo4j directly.
    Each tool dispatch must go through self.db.* or self.graph.*.
    We inject mocks and verify the correct service method is called.
    """

    @pytest.fixture
    def mock_db(self):
        db = MagicMock(spec=RelationalService)
        db.query_national_rail_availability.return_value = []
        db.query_metro_schedules.return_value = []
        db.query_available_seats.return_value = []
        return db

    @pytest.fixture
    def mock_graph(self):
        graph = MagicMock(spec=GraphService)
        graph.query_shortest_route.return_value = {}
        graph.query_cheapest_route.return_value = {}
        graph.query_interchange_path.return_value = {}
        graph.query_alternative_routes.return_value = []
        graph.query_delay_ripple.return_value = []
        return graph

    @pytest.fixture
    def agent(self, mock_db, mock_graph):
        return TransitFlowAgent(db_service=mock_db, graph_service=mock_graph)

    # ── Relational tool paths ─────────────────────────────────────────────────

    def test_nr_availability_calls_db_service(self, agent, mock_db):
        agent._execute_tool("check_national_rail_availability",
                            {"origin_id": "NR01", "destination_id": "NR05"})
        mock_db.query_national_rail_availability.assert_called_once()

    def test_metro_availability_calls_db_service(self, agent, mock_db):
        agent._execute_tool("check_metro_availability",
                            {"origin_id": "MS01", "destination_id": "MS09"})
        mock_db.query_metro_schedules.assert_called_once_with(
            origin_id="MS01", destination_id="MS09"
        )

    def test_nr_availability_does_not_call_graph_service(self, agent, mock_graph):
        agent._execute_tool("check_national_rail_availability",
                            {"origin_id": "NR01", "destination_id": "NR05"})
        mock_graph.query_shortest_route.assert_not_called()

    def test_available_seats_calls_db_service(self, agent, mock_db):
        agent._execute_tool("get_available_seats",
                            {"schedule_id": "NR_SCH01", "travel_date": "2026-06-01",
                             "fare_class": "standard"})
        mock_db.query_available_seats.assert_called_once_with(
            schedule_id="NR_SCH01", travel_date="2026-06-01", fare_class="standard"
        )

    # ── Graph tool paths ──────────────────────────────────────────────────────

    def test_find_route_time_calls_graph_service(self, agent, mock_graph):
        agent._execute_tool("find_route",
                            {"origin_id": "NR01", "destination_id": "NR05",
                             "optimise_by": "time"})
        mock_graph.query_shortest_route.assert_called_once()

    def test_find_route_cost_calls_graph_service(self, agent, mock_graph):
        agent._execute_tool("find_route",
                            {"origin_id": "NR01", "destination_id": "NR05",
                             "optimise_by": "cost"})
        mock_graph.query_cheapest_route.assert_called_once()

    def test_find_route_cross_network_calls_interchange_path(self, agent, mock_graph):
        """Cross-network (MS→NR) must use query_interchange_path, not shortest/cheapest."""
        agent._execute_tool("find_route",
                            {"origin_id": "MS01", "destination_id": "NR01"})
        mock_graph.query_interchange_path.assert_called_once_with("MS01", "NR01")
        mock_graph.query_shortest_route.assert_not_called()
        mock_graph.query_cheapest_route.assert_not_called()

    def test_find_alternative_routes_calls_graph_service(self, agent, mock_graph):
        agent._execute_tool("find_alternative_routes",
                            {"origin_id": "NR01", "destination_id": "NR05",
                             "avoid_station_id": "NR03"})
        mock_graph.query_alternative_routes.assert_called_once_with(
            origin_id="NR01", destination_id="NR05",
            avoid_station_id="NR03", network="auto"
        )

    def test_delay_ripple_calls_graph_service(self, agent, mock_graph):
        agent._execute_tool("get_delay_ripple", {"station_id": "NR03"})
        mock_graph.query_delay_ripple.assert_called_once_with(
            delayed_station_id="NR03", hops=2
        )

    def test_graph_tool_does_not_call_db_service(self, agent, mock_db):
        agent._execute_tool("find_route",
                            {"origin_id": "NR01", "destination_id": "NR05"})
        mock_db.query_national_rail_availability.assert_not_called()

    # ── error_handler active with injected services ───────────────────────────

    def test_error_handler_catches_exception_from_mock_db(self, agent, mock_db):
        """error_handler must still intercept exceptions raised by injected services."""
        exc = DatabaseException("DB timeout", "DB_TIMEOUT")
        mock_db.query_national_rail_availability.side_effect = exc
        raw = agent._execute_tool("check_national_rail_availability",
                                  {"origin_id": "NR01", "destination_id": "NR05"})
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "DB_TIMEOUT"

    def test_error_handler_catches_route_not_found_from_mock_graph(self, agent, mock_graph):
        exc = RouteNotFoundException("No path", "ROUTE_NOT_FOUND")
        mock_graph.query_shortest_route.side_effect = exc
        raw = agent._execute_tool("find_route",
                                  {"origin_id": "NR01", "destination_id": "NR05"})
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "ROUTE_NOT_FOUND"

    def test_unknown_tool_returns_error_json(self, agent):
        raw = agent._execute_tool("nonexistent_tool", {})
        result = json.loads(raw)
        assert "error" in result


# ═════════════════════════════════════════════════════════════════════════════
# 6. Agent source has no direct driver imports (coupling check)
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentNoCouplingToDrivers:
    """
    DoD: 'TransitFlowAgent program code must not directly call any psycopg2 or
    neo4j native driver' — verified by inspecting the agent module source.
    """

    def test_agent_module_does_not_import_psycopg2(self):
        source = inspect.getsource(_agent_module)
        # Check for actual import statements, not mere mentions in docstrings/comments.
        assert not re.search(r"^\s*(import psycopg2|from psycopg2)", source, re.MULTILINE), (
            "skeleton/agent.py must not have a psycopg2 import statement"
        )

    def test_agent_module_does_not_import_neo4j_driver(self):
        source = inspect.getsource(_agent_module)
        assert "from neo4j" not in source and "import neo4j" not in source, (
            "skeleton/agent.py must not import the neo4j driver directly"
        )

    def test_agent_module_does_not_import_databases_relational_queries(self):
        source = inspect.getsource(_agent_module)
        assert "from databases.relational.queries import" not in source, (
            "skeleton/agent.py must not import query functions directly; "
            "use the injected db_service instead"
        )

    def test_agent_module_does_not_import_databases_graph_queries(self):
        source = inspect.getsource(_agent_module)
        assert "from databases.graph.queries import" not in source, (
            "skeleton/agent.py must not import graph query functions directly; "
            "use the injected graph_service instead"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 7. Module-level run_agent — backward compatibility
# ═════════════════════════════════════════════════════════════════════════════

class TestModuleLevelRunAgent:
    """Module-level run_agent must remain callable and delegate to _default_agent."""

    def test_run_agent_is_callable(self):
        assert callable(run_agent)

    def test_default_agent_is_transit_flow_agent(self):
        assert isinstance(_default_agent, TransitFlowAgent)

    def test_default_agent_db_is_postgresql_service(self):
        assert isinstance(_default_agent.db, PostgreSQLService)

    def test_default_agent_graph_is_neo4j_service(self):
        assert isinstance(_default_agent.graph, Neo4jService)

    def test_run_agent_delegates_to_default_agent_run(self):
        """run_agent must call _default_agent.run() — verified via mock."""
        with patch.object(_default_agent, "run", return_value=("reply", [])) as mock_run:
            result = run_agent("hello", [])
        mock_run.assert_called_once_with("hello", [], False, None, None)
        assert result == ("reply", [])


if __name__ == "__main__":
    smoke = [
        # Hierarchy
        TestDatabaseServiceHierarchy().test_postgresql_service_is_database_service_subclass,
        TestDatabaseServiceHierarchy().test_neo4j_service_is_database_service_subclass,
        TestDatabaseServiceHierarchy().test_at_least_two_concrete_database_service_subclasses,
        # Service delegation
        TestPostgreSQLService().test_stores_dsn,
        TestNeo4jService().test_stores_uri,
        # DI
        TestTransitFlowAgentDI().test_execute_tool_has_wrapped_attribute(
            TransitFlowAgent(MagicMock(spec=RelationalService), MagicMock(spec=GraphService))
        ),
        # Coupling
        TestAgentNoCouplingToDrivers().test_agent_module_does_not_import_psycopg2,
        TestAgentNoCouplingToDrivers().test_agent_module_does_not_import_databases_relational_queries,
        # Backward compat
        TestModuleLevelRunAgent().test_default_agent_is_transit_flow_agent,
    ]
    print(f"\n✓ Smoke tests listed: {len(smoke)} checks")
    print("Run full suite with: pytest tests/unit/test_phase_3.2_solid_refactor.py -v")
