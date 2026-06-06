"""
TransitFlow — Database Service Layer (SOLID Refactor, Stage 3.2)
================================================================
Defines the abstract interface for all database access and provides
concrete implementations that delegate to the existing query modules.

WHY THIS EXISTS:
  The agent previously imported query functions directly, coupling it
  tightly to specific database drivers.  This layer breaks that coupling
  so that any DatabaseService implementation can be substituted — useful
  for testing (mock services) and future driver migrations.

CLASS HIERARCHY:
  DatabaseService          ← marker base (all services inherit from this)
    RelationalService      ← abstract interface for PostgreSQL operations
      PostgreSQLService    ← delegates to databases/relational/queries.py
    GraphService           ← abstract interface for Neo4j operations
      Neo4jService         ← delegates to databases/graph/queries.py
"""

# TASK 6 EXTENSION (Stage 3 robustness layer): DI database-service abstraction. See TASK6.md §B.

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import Optional


# ── Abstract base ─────────────────────────────────────────────────────────────

class DatabaseService(ABC):
    """Marker base class.  All concrete services inherit from this."""
    pass


# ── Relational interface ──────────────────────────────────────────────────────

class RelationalService(DatabaseService):
    """Abstract interface for relational (PostgreSQL + pgvector) operations."""

    @abstractmethod
    def query_national_rail_availability(
        self, origin_id: str, destination_id: str, travel_date: Optional[str] = None
    ): ...

    @abstractmethod
    def query_national_rail_fare(
        self, schedule_id: str, fare_class: str, stops_travelled: int
    ): ...

    @abstractmethod
    def query_metro_schedules(self, origin_id: str, destination_id: str): ...

    @abstractmethod
    def query_metro_fare(self, schedule_id: str, stops_travelled: int): ...

    @abstractmethod
    def query_available_seats(
        self, schedule_id: str, travel_date: str, fare_class: str
    ): ...

    @abstractmethod
    def auto_select_adjacent_seats(
        self, schedule_id: str, travel_date: str, fare_class: str, num_seats: int
    ): ...

    @abstractmethod
    def query_user_profile(self, email: str): ...

    @abstractmethod
    def query_user_bookings(self, email: str): ...

    @abstractmethod
    def execute_booking(
        self,
        user_id: str,
        schedule_id: str,
        origin_station_id: str,
        destination_station_id: str,
        travel_date: str,
        fare_class: str,
        seat_id: str,
        ticket_type: str,
    ): ...

    @abstractmethod
    def execute_cancellation(self, booking_id: str, user_id: str): ...

    @abstractmethod
    def query_policy_vector_search(self, embedding): ...


# ── Graph interface ───────────────────────────────────────────────────────────

class GraphService(DatabaseService):
    """Abstract interface for graph (Neo4j) operations."""

    @abstractmethod
    def query_shortest_route(
        self, origin_id: str, destination_id: str, network: str = "auto"
    ): ...

    @abstractmethod
    def query_cheapest_route(
        self, origin_id: str, destination_id: str, network: str = "auto"
    ): ...

    @abstractmethod
    def query_alternative_routes(
        self,
        origin_id: str,
        destination_id: str,
        avoid_station_id: str,
        network: str = "auto",
    ): ...

    @abstractmethod
    def query_interchange_path(self, origin_id: str, destination_id: str): ...

    @abstractmethod
    def query_delay_ripple(self, delayed_station_id: str, hops: int = 2): ...


# ── Concrete: PostgreSQL ──────────────────────────────────────────────────────

class PostgreSQLService(RelationalService):
    """
    Relational service backed by PostgreSQL.
    Delegates to databases/relational/queries.py.
    The dsn is stored on the instance; the underlying query functions read
    their connection string from skeleton.config at call time.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        # importlib.import_module short-circuits at sys.modules, making test-time
        # stubbing reliable without needing real intermediate packages loaded.
        self._q = importlib.import_module("databases.relational.queries")

    def query_national_rail_availability(self, origin_id, destination_id, travel_date=None):
        return self._q.query_national_rail_availability(origin_id, destination_id, travel_date)

    def query_national_rail_fare(self, schedule_id, fare_class, stops_travelled):
        return self._q.query_national_rail_fare(schedule_id, fare_class, stops_travelled)

    def query_metro_schedules(self, origin_id, destination_id):
        return self._q.query_metro_schedules(origin_id, destination_id)

    def query_metro_fare(self, schedule_id, stops_travelled):
        return self._q.query_metro_fare(schedule_id, stops_travelled)

    def query_available_seats(self, schedule_id, travel_date, fare_class):
        return self._q.query_available_seats(schedule_id, travel_date, fare_class)

    def auto_select_adjacent_seats(self, schedule_id, travel_date, fare_class, num_seats):
        return self._q.auto_select_adjacent_seats(schedule_id, travel_date, fare_class, num_seats)

    def query_user_profile(self, email):
        return self._q.query_user_profile(email)

    def query_user_bookings(self, email):
        return self._q.query_user_bookings(email)

    def execute_booking(
        self, user_id, schedule_id, origin_station_id, destination_station_id,
        travel_date, fare_class, seat_id, ticket_type,
    ):
        return self._q.execute_booking(
            user_id, schedule_id, origin_station_id, destination_station_id,
            travel_date, fare_class, seat_id, ticket_type,
        )

    def execute_cancellation(self, booking_id, user_id):
        return self._q.execute_cancellation(booking_id, user_id)

    def query_policy_vector_search(self, embedding):
        return self._q.query_policy_vector_search(embedding)

    # TASK 6 EXTENSION (§C): pgvector tool-router similarity lookup.
    def query_tool_candidates(self, embedding, top_k=4):
        return self._q.query_tool_candidates(embedding, top_k)


# ── Concrete: Neo4j ───────────────────────────────────────────────────────────

class Neo4jService(GraphService):
    """
    Graph service backed by Neo4j.
    Delegates to databases/graph/queries.py.
    The uri is stored on the instance; the underlying driver reads its
    connection details from skeleton.config at call time.
    """

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self._q = importlib.import_module("databases.graph.queries")

    def query_shortest_route(self, origin_id, destination_id, network="auto"):
        return self._q.query_shortest_route(origin_id, destination_id, network)

    def query_cheapest_route(self, origin_id, destination_id, network="auto"):
        return self._q.query_cheapest_route(origin_id, destination_id, network)

    def query_alternative_routes(self, origin_id, destination_id, avoid_station_id, network="auto"):
        return self._q.query_alternative_routes(origin_id, destination_id, avoid_station_id, network)

    def query_interchange_path(self, origin_id, destination_id):
        return self._q.query_interchange_path(origin_id, destination_id)

    def query_delay_ripple(self, delayed_station_id, hops=2):
        return self._q.query_delay_ripple(delayed_station_id, hops)
