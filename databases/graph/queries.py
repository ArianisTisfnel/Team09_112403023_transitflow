"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from databases.graph.connection_pool import get_pool


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

_CYPHER_SHORTEST_ROUTE = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.dijkstra(
    origin,
    destination,
    'CONNECTS_TO|INTERCHANGE',
    'travel_time_min'
) YIELD path, weight
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations,
    weight AS total_travel_time_min,
    size(relationships(path)) AS num_legs
"""


def _empty_route_result(origin_id: str, destination_id: str, error: str) -> dict:
    return {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "error": error,
        "station_ids": [],
        "stations": [],
        "legs": [],
    }


def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra over CONNECTS_TO and INTERCHANGE edges with
    travel_time_min as the weight (APOC plugin enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (currently unused —
                         Dijkstra naturally finds the best path regardless of
                         which network the endpoints sit on)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_travel_time_min, num_legs, station_ids,
                        stations (list of {station_id, name, network_type}),
                        legs (list of from/to station dicts).
        On no path or error: found=False with an error key.
    """
    try:
        with get_pool() as driver:
            with driver.session() as session:
                record = session.run(
                    _CYPHER_SHORTEST_ROUTE,
                    origin_id=origin_id,
                    destination_id=destination_id,
                ).single()

                if record is None:
                    return _empty_route_result(
                        origin_id,
                        destination_id,
                        f"No path found from {origin_id} to {destination_id}",
                    )

                station_ids = record["station_ids"]
                stations = record["stations"]
                total_time = record["total_travel_time_min"]
                num_legs = record["num_legs"]

                legs = []
                for i in range(len(station_ids) - 1):
                    frm = stations[i]
                    to = stations[i + 1]
                    legs.append({
                        "from_station_id": frm["station_id"],
                        "from_station_name": frm["name"],
                        "to_station_id": to["station_id"],
                        "to_station_name": to["name"],
                        "from_network": frm["network_type"],
                        "to_network": to["network_type"],
                    })

                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_travel_time_min": int(total_time) if total_time is not None else 0,
                    "num_legs": num_legs,
                    "station_ids": station_ids,
                    "stations": stations,
                    "legs": legs,
                }

    except Exception as e:
        return _empty_route_result(
            origin_id,
            destination_id,
            f"Error querying shortest route: {str(e)}",
        )


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

_CYPHER_STATION_CONNECTIONS = """
MATCH (s:Station {station_id: $station_id})-[r]->(n:Station)
RETURN
    s.station_id      AS from_station_id,
    s.name            AS from_station_name,
    s.network_type    AS from_network,
    n.station_id      AS to_station_id,
    n.name            AS to_station_name,
    n.network_type    AS to_network,
    type(r)           AS relationship_type,
    r.travel_time_min AS travel_time_min,
    r.line            AS line
ORDER BY n.station_id ASC
"""


def query_station_connections(station_id: str) -> list[dict]:
    """
    List all outgoing direct connections from a given station, including both
    CONNECTS_TO (same-network rail/metro segments) and INTERCHANGE
    (cross-network walking transfers).

    Args:
        station_id: e.g. "MS01" or "NR01"

    Returns:
        list of dicts each containing:
          from_station_id, from_station_name, from_network,
          to_station_id, to_station_name, to_network,
          relationship_type ("CONNECTS_TO" or "INTERCHANGE"),
          travel_time_min, line (None for INTERCHANGE).
        Returns [] when the station has no outgoing edges or does not exist.
    """
    try:
        with get_pool() as driver:
            with driver.session() as session:
                records = session.run(
                    _CYPHER_STATION_CONNECTIONS,
                    station_id=station_id,
                ).data()
                return records
    except Exception:
        return []
