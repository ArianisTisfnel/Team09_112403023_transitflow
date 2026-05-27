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

from datetime import datetime, timedelta
from typing import Optional

from databases.graph.connection_pool import get_pool


_MIN_INTERCHANGE_MIN = 15  # minimum walking time between platforms (docs/15, docs/18)


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

_CYPHER_ALTERNATIVE_ROUTES = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    5
) YIELD path
WHERE length(path) > 0
  AND NOT any(node IN nodes(path) WHERE node.station_id = $avoid_station_id)
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations
LIMIT $max_routes
"""


def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[dict]:
    """
    Find up to `max_routes` paths between two stations that **do not pass through**
    `avoid_station_id`. Models routing around a closed / delayed station.

    Uses apoc.algo.allSimplePaths (max depth 5) with a node-list filter to exclude
    the avoided station. Returns an empty list when no alternative exists or on
    error — never raises.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03" (a station present on the normal path)
        network:           "metro", "rail", or "auto" (currently unused —
                           allSimplePaths traverses any relationship type
                           passed to it; both networks are reachable)
        max_routes:        upper bound on returned routes (default 3)

    Returns:
        list of dicts, each containing:
          station_ids, stations, legs, avoid_station_id.
        Returns [] when no path avoids the station, or on any exception.
    """
    try:
        with get_pool() as driver:
            with driver.session() as session:
                records = session.run(
                    _CYPHER_ALTERNATIVE_ROUTES,
                    origin_id=origin_id,
                    destination_id=destination_id,
                    avoid_station_id=avoid_station_id,
                    max_routes=max_routes,
                ).data()

                routes = []
                for rec in records:
                    station_ids = rec["station_ids"]
                    stations = rec["stations"]

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

                    routes.append({
                        "station_ids": station_ids,
                        "stations": stations,
                        "legs": legs,
                        "avoid_station_id": avoid_station_id,
                    })

                return routes

    except Exception:
        return []


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

_CYPHER_INTERCHANGE_PATH_NODES = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    10
) YIELD path
WHERE length(path) > 0
  AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations,
    [rel IN relationships(path) | rel.travel_time_min] AS travel_times
LIMIT 1
"""

_CYPHER_INTERCHANGE_PATH_RELS = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.allSimplePaths(
    origin, destination,
    'CONNECTS_TO|INTERCHANGE',
    10
) YIELD path
WHERE length(path) > 0
  AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE')
UNWIND relationships(path) AS rel
WITH path, rel, startNode(rel) AS from_node, endNode(rel) AS to_node, type(rel) AS rel_type
RETURN
    from_node.station_id  AS from_id,
    from_node.name        AS from_name,
    from_node.network_type AS from_network,
    to_node.station_id    AS to_id,
    to_node.name          AS to_name,
    to_node.network_type  AS to_network,
    rel_type,
    rel.travel_time_min   AS travel_time
LIMIT 20
"""


def _empty_interchange_result(origin_id: str, destination_id: str, error: str) -> dict:
    return {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "station_ids": [],
        "stations": [],
        "interchange_points": [],
        "total_travel_time_min": 0,
        "num_legs": 0,
        "legs": [],
        "error": error,
    }


def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between two stations that **must** include at least one
    INTERCHANGE relationship (i.e. the path crosses the metro / national rail
    boundary at least once). Models user intent like "I want to use both
    networks on this trip".

    Implementation: two-pass query — first pass picks one matching path and
    pulls its node sequence + per-edge times; second pass enumerates every
    relationship along that path so we can label each leg's type and surface
    the interchange points explicitly.

    Args:
        origin_id:       e.g. "MS01" (metro) or "NR05" (rail)
        destination_id:  e.g. "NR05" (rail) or "MS09" (metro)

    Returns:
        dict with: found, origin_id, destination_id, station_ids, stations,
                   interchange_points (list of boundary-crossing leg dicts),
                   total_travel_time_min, num_legs, legs.
        On no interchange path or error: found=False with an error key.
    """
    try:
        with get_pool() as driver:
            with driver.session() as session:
                # ── Pass 1: find one path + node/time data ───────────────────
                record = session.run(
                    _CYPHER_INTERCHANGE_PATH_NODES,
                    origin_id=origin_id,
                    destination_id=destination_id,
                ).single()

                if record is None:
                    return _empty_interchange_result(
                        origin_id,
                        destination_id,
                        f"No interchange path found from {origin_id} to {destination_id}",
                    )

                station_ids = record["station_ids"]
                stations = record["stations"]
                travel_times = record["travel_times"] or []
                total_time = sum(t for t in travel_times if t is not None)

                # ── Pass 2: relationship details (type + endpoints) ──────────
                rel_records = session.run(
                    _CYPHER_INTERCHANGE_PATH_RELS,
                    origin_id=origin_id,
                    destination_id=destination_id,
                ).data()

                # Build a (from_id, to_id) -> leg-dict lookup
                legs_map = {}
                for r in rel_records:
                    key = (r["from_id"], r["to_id"])
                    if key in legs_map:
                        continue  # keep first match for this directed pair
                    legs_map[key] = {
                        "from_station_id": r["from_id"],
                        "from_station_name": r["from_name"],
                        "to_station_id": r["to_id"],
                        "to_station_name": r["to_name"],
                        "from_network": r["from_network"],
                        "to_network": r["to_network"],
                        "relationship_type": r["rel_type"],
                        "travel_time_min": r["travel_time"] or 0,
                    }

                # Assemble legs in path order; collect INTERCHANGE points
                legs = []
                interchange_points = []
                for i in range(len(station_ids) - 1):
                    key = (station_ids[i], station_ids[i + 1])
                    if key in legs_map:
                        leg = legs_map[key]
                    else:
                        # Fallback (should be rare): synthesize from stations array
                        frm = stations[i]
                        to = stations[i + 1]
                        leg = {
                            "from_station_id": frm["station_id"],
                            "from_station_name": frm["name"],
                            "to_station_id": to["station_id"],
                            "to_station_name": to["name"],
                            "from_network": frm["network_type"],
                            "to_network": to["network_type"],
                            "relationship_type": "UNKNOWN",
                            "travel_time_min": 0,
                        }
                    legs.append(leg)

                    if leg["relationship_type"] == "INTERCHANGE":
                        interchange_points.append({
                            "from_station_id": leg["from_station_id"],
                            "from_station_name": leg["from_station_name"],
                            "from_network": leg["from_network"],
                            "to_station_id": leg["to_station_id"],
                            "to_station_name": leg["to_station_name"],
                            "to_network": leg["to_network"],
                            "travel_time_min": leg["travel_time_min"],
                        })

                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "station_ids": station_ids,
                    "stations": stations,
                    "interchange_points": interchange_points,
                    "total_travel_time_min": int(total_time),
                    "num_legs": len(legs),
                    "legs": legs,
                }

    except Exception as e:
        return _empty_interchange_result(
            origin_id,
            destination_id,
            f"Error querying interchange path: {str(e)}",
        )


def _parse_time_to_minutes(value) -> Optional[int]:
    """Parse 'HH:MM' or 'HH:MM:SS' to total minutes since midnight. Return None on failure."""
    if value is None:
        return None
    s = str(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.hour * 60 + dt.minute
        except ValueError:
            continue
    return None


def validate_interchange_feasibility(path_details: dict) -> bool:
    """
    Check that every interchange in a path has at least 15 minutes of transfer
    window — the minimum walking time between platforms in this network.

    Supports two payload layouts:

      Layout A — path_details["legs"]: a list of leg dicts. INTERCHANGE legs
          have relationship_type == "INTERCHANGE" and travel_time_min must be
          >= 15.

      Layout B — path_details["interchange_points"]: a list of transfer-point
          dicts. Each point may carry either:
            - explicit arrival_time / departure_time strings (HH:MM or
              HH:MM:SS), in which case the gap between them must be >= 15
              (the gap is calculated in absolute minutes, with cross-midnight
              correction);
            - or a precomputed transfer_time_min that must be >= 15.

    A path with no INTERCHANGE leg is considered feasible (nothing to validate).

    Args:
        path_details: typically the dict returned by query_interchange_path,
                      but any dict carrying legs or interchange_points works.

    Returns:
        True if every interchange meets the minimum, False otherwise.
    """
    # Layout A: legs
    for leg in path_details.get("legs", []) or []:
        if leg.get("relationship_type") != "INTERCHANGE":
            continue
        if (leg.get("travel_time_min") or 0) < _MIN_INTERCHANGE_MIN:
            return False

    # Layout B: interchange_points (timetable-aware)
    for point in path_details.get("interchange_points", []) or []:
        arrival = point.get("arrival_time")
        departure = point.get("departure_time")

        if arrival and departure:
            arr_min = _parse_time_to_minutes(arrival)
            dep_min = _parse_time_to_minutes(departure)
            if arr_min is not None and dep_min is not None:
                gap = dep_min - arr_min
                if gap < 0:
                    gap += 24 * 60  # cross-midnight correction
                if gap < _MIN_INTERCHANGE_MIN:
                    return False
                continue
            # fall through if parse failed — try transfer_time_min below

        if "transfer_time_min" in point:
            if (point.get("transfer_time_min") or 0) < _MIN_INTERCHANGE_MIN:
                return False

    return True


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
