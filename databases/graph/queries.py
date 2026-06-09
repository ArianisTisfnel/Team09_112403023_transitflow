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

# TASK 6 EXTENSION: shared Neo4j connection pool. See TASK6.md + DESIGN_DOC §7.
from databases.graph.connection_pool import get_pool

# Cross-track imports for query_cheapest_route (docs/20). These functions live
# in databases.relational.queries — owned by Track A. Importing them is safe
# even before they are implemented because Python only complains at call time,
# not import time; the stub raises NotImplementedError, which is caught by the
# per-segment fallback below.
from databases.relational.queries import (
    query_metro_fare,
    query_metro_schedules,
    query_national_rail_availability,
    query_national_rail_fare,
)


_MIN_INTERCHANGE_MIN = 15  # minimum walking time between platforms (docs/15, docs/18)

# Fare fallback defaults (docs/20). Used when the Track A fare functions return
# nothing or raise — typical reasons include the segment crossing networks
# (no through-service) and Track A still being on stubs.
_DEFAULT_METRO_SEGMENT_FARE_USD = 1.50
_DEFAULT_RAIL_SEGMENT_FARE_USD = 5.00
_CHEAPEST_PATH_MAX_HOPS = 5
_CHEAPEST_PATH_MAX_EVAL = 10
_CHEAPEST_TOP_K = 3


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

_CYPHER_SHORTEST_ROUTE = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.dijkstra(
    origin,
    destination,
    'METRO_LINK|RAIL_LINK|INTERCHANGE_TO',
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
    Uses apoc.algo.dijkstra over METRO_LINK / RAIL_LINK / INTERCHANGE_TO edges
    with travel_time_min as the weight (APOC plugin enabled in docker-compose.yml).

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

                total_time_min = int(total_time) if total_time is not None else 0

                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_travel_time_min": total_time_min,
                    # Spec-facing aliases: the grading guide names the route as
                    # "path" (list) + "total_time_min" (numeric). Provide both
                    # alongside our richer station_ids/total_travel_time_min keys.
                    "path": station_ids,
                    "total_time_min": total_time_min,
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


# ── CHEAPEST ROUTE (allSimplePaths + per-segment fare lookup) ─────────────────

_CYPHER_CHEAPEST_PATHS = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.allSimplePaths(
    origin, destination,
    'METRO_LINK|RAIL_LINK|INTERCHANGE_TO',
    $max_hops
) YIELD path
WHERE length(path) > 0
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations
LIMIT $max_eval
"""


def _segment_fare_usd(from_id: str, to_id: str, fare_class: str) -> float:
    """
    Compute the fare for a single graph edge by routing through the Track A
    fare functions. Falls back to docs/20-defined defaults whenever Track A
    returns nothing, raises, or the segment crosses networks (in which case
    no through-service exists by definition).
    """
    is_metro_segment = from_id.startswith("MS") and to_id.startswith("MS")

    try:
        if is_metro_segment:
            schedules = query_metro_schedules(from_id, to_id)
            if schedules:
                fare = query_metro_fare(schedules[0]["schedule_id"], 1)
                if fare and "total_fare_usd" in fare:
                    return float(fare["total_fare_usd"])
            return _DEFAULT_METRO_SEGMENT_FARE_USD

        # National rail segment, or cross-network (MS↔NR via INTERCHANGE)
        avail = query_national_rail_availability(from_id, to_id)
        if avail:
            fare = query_national_rail_fare(avail[0]["schedule_id"], fare_class, 1)
            if fare and "total_fare_usd" in fare:
                return float(fare["total_fare_usd"])
        return _DEFAULT_RAIL_SEGMENT_FARE_USD

    except Exception:
        # NotImplementedError (Track A stubs), connection issues, key errors,
        # type errors — anything bubbling up from cross-track calls falls back
        # to a default so the cheapest-route algorithm can still progress.
        return _DEFAULT_RAIL_SEGMENT_FARE_USD


def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path(s) between two stations by enumerating all simple
    paths (max depth 5, max 10 evaluated), costing each segment via the Track
    A fare functions, and returning the top 3 sorted by total fare.

    Segment cost rules (per docs/20):
      - Metro segment (MS->MS):   query_metro_schedules + query_metro_fare
      - Rail / cross-network:     query_national_rail_availability + query_national_rail_fare
      - Any Track-A failure:      fall back to default per docs/20

    Args:
        origin_id:       e.g. "NR01" or "MS01"
        destination_id:  e.g. "NR05" or "MS09"
        network:         "metro" / "rail" / "auto" (currently unused —
                         allSimplePaths spans whichever relationship types
                         appear on viable paths)
        fare_class:      "standard" or "first" (passed through to
                         query_national_rail_fare)

    Returns:
        dict with: found, origin_id, destination_id,
                   cheapest_routes (list of top-3 routes sorted by total_fare_usd,
                       each with station_ids / stations / total_fare_usd / legs),
                   routes_found_total, num_cheapest.
        On no path / error: found=False, cheapest_routes=[], plus error key.
    """
    try:
        with get_pool() as driver:
            with driver.session() as session:
                path_records = session.run(
                    _CYPHER_CHEAPEST_PATHS,
                    origin_id=origin_id,
                    destination_id=destination_id,
                    max_hops=_CHEAPEST_PATH_MAX_HOPS,
                    max_eval=_CHEAPEST_PATH_MAX_EVAL,
                ).data()

                if not path_records:
                    return {
                        "found": False,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "cheapest_routes": [],
                        "routes_found_total": 0,
                        "num_cheapest": 0,
                        "error": f"No path found from {origin_id} to {destination_id}",
                    }

                costed_routes = []
                for record in path_records:
                    station_ids = record["station_ids"]
                    stations = record["stations"]

                    total_fare = 0.0
                    legs = []
                    for i in range(len(station_ids) - 1):
                        seg_fare = _segment_fare_usd(
                            station_ids[i],
                            station_ids[i + 1],
                            fare_class,
                        )
                        total_fare += seg_fare
                        legs.append({
                            "from_station_id": stations[i]["station_id"],
                            "from_station_name": stations[i]["name"],
                            "to_station_id": stations[i + 1]["station_id"],
                            "to_station_name": stations[i + 1]["name"],
                            "segment_fare_usd": round(seg_fare, 2),
                        })

                    costed_routes.append({
                        "station_ids": station_ids,
                        "stations": stations,
                        "total_fare_usd": round(total_fare, 2),
                        "legs": legs,
                    })

                costed_routes.sort(key=lambda r: r["total_fare_usd"])
                top = costed_routes[:_CHEAPEST_TOP_K]

                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "cheapest_routes": top,
                    "routes_found_total": len(costed_routes),
                    "num_cheapest": len(top),
                }

    except Exception as e:
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "cheapest_routes": [],
            "routes_found_total": 0,
            "num_cheapest": 0,
            "error": f"Error querying cheapest route: {str(e)}",
        }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

_CYPHER_ALTERNATIVE_ROUTES = """
MATCH (origin:Station {station_id: $origin_id})
MATCH (destination:Station {station_id: $destination_id})
CALL apoc.algo.allSimplePaths(
    origin, destination,
    'METRO_LINK|RAIL_LINK|INTERCHANGE_TO',
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
    'METRO_LINK|RAIL_LINK|INTERCHANGE_TO',
    10
) YIELD path
WHERE length(path) > 0
  AND any(rel IN relationships(path) WHERE type(rel) = 'INTERCHANGE_TO')
RETURN
    [n IN nodes(path) | n.station_id] AS station_ids,
    [n IN nodes(path) | {
        station_id: n.station_id,
        name: n.name,
        network_type: n.network_type
    }] AS stations,
    [rel IN relationships(path) | rel.travel_time_min] AS travel_times,
    [rel IN relationships(path) | {
        rel_type:    type(rel),
        travel_time: rel.travel_time_min
    }] AS legs
LIMIT 1
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

                # Build the legs from the SAME path. nodes(path) and
                # relationships(path) share an order, so the i-th relationship
                # connects stations[i] -> stations[i+1]; we take the endpoints from
                # the node list (path-traversal direction) and only the type/time
                # from the relationship. A previous version ran a second
                # allSimplePaths query for the relationships, which could return a
                # different path and lose the INTERCHANGE labels entirely.
                rels = record["legs"]
                legs = []
                interchange_points = []
                for i, r in enumerate(rels):
                    frm = stations[i]
                    to = stations[i + 1]
                    leg = {
                        "from_station_id": frm["station_id"],
                        "from_station_name": frm["name"],
                        "to_station_id": to["station_id"],
                        "to_station_name": to["name"],
                        "from_network": frm["network_type"],
                        "to_network": to["network_type"],
                        "relationship_type": r["rel_type"],
                        "travel_time_min": r["travel_time"] or 0,
                    }
                    legs.append(leg)

                    if leg["relationship_type"] == "INTERCHANGE_TO":
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
          have relationship_type == "INTERCHANGE_TO" and travel_time_min must be
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
        if leg.get("relationship_type") != "INTERCHANGE_TO":
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

_CYPHER_RIPPLE_CENTER = """
MATCH (center:Station {station_id: $station_id})
RETURN center.station_id   AS station_id,
       center.name         AS name,
       center.network_type AS network_type
"""


def _empty_ripple_result(station_id: str, hops: int, error: Optional[str] = None) -> dict:
    result = {
        "affected_station_id": station_id,
        "affected_station": None,
        "primary_impact_zone": [],
        "secondary_impact_zone": [],
        "total_affected_stations": 0,
        "total_hops_searched": hops,
    }
    if error is not None:
        result["error"] = error
    return result


def query_delay_ripple(affected_station_id: str, hops: int = 2) -> dict:
    """
    Find all stations affected by a disruption at `affected_station_id`,
    classified by network distance:
      - primary_impact_zone:   directly connected stations (1 hop away)
      - secondary_impact_zone: indirectly connected stations (2+ hops away)

    Uses three Cypher passes:
      1. Confirm the centre station exists (return early with error if not).
      2. Variable-length path traversal [*1..hops] to enumerate all neighbours
         within N hops (deduplicated by station_id).
      3. shortestPath() per neighbour to compute its exact hop count, used
         for primary/secondary classification.

    Note: Neo4j forbids parameters inside variable-length path patterns, so
    `hops` is embedded into the query string via f-string. `int()` coercion
    on input rules out injection.

    Args:
        affected_station_id: centre of the disruption, e.g. "NR03" or "MS01"
        hops: search radius in hops (default 2)

    Returns:
        dict with affected_station_id, affected_station,
        primary_impact_zone, secondary_impact_zone, total_affected_stations,
        total_hops_searched. On missing station / error: error key added,
        affected_station=None, both zones empty.
    """
    # Coerce + clamp hops defensively to 0..5. hops=0 is a valid request meaning
    # "only the delayed station itself, no neighbours" (handled as an early return
    # below); 1..5 enumerate the surrounding impact zones.
    try:
        hops = max(0, min(int(hops), 5))
    except (TypeError, ValueError):
        hops = 2

    try:
        with get_pool() as driver:
            with driver.session() as session:
                # ── Pass 1: centre station ───────────────────────────────────
                center_record = session.run(
                    _CYPHER_RIPPLE_CENTER,
                    station_id=affected_station_id,
                ).single()

                if center_record is None:
                    return _empty_ripple_result(
                        affected_station_id,
                        hops,
                        error=f"Affected station {affected_station_id} not found",
                    )

                affected_station = {
                    "station_id": center_record["station_id"],
                    "name": center_record["name"],
                    "network_type": center_record["network_type"],
                }

                # hops=0 → only the delayed station itself, no ripple. Return
                # early (a variable-length pattern [*1..0] would also be invalid
                # Cypher), so neighbours are never enumerated.
                if hops == 0:
                    return {
                        "affected_station_id": affected_station_id,
                        "affected_station": affected_station,
                        "primary_impact_zone": [],
                        "secondary_impact_zone": [],
                        "total_affected_stations": 0,
                        "total_hops_searched": 0,
                    }

                # ── Pass 2: all neighbours within N hops ─────────────────────
                ripple_query = (
                    "MATCH (center:Station {{station_id: $station_id}}) "
                    "MATCH (center)-[*1..{hops}]-(neighbor:Station) "
                    "WHERE neighbor.station_id <> center.station_id "
                    "RETURN DISTINCT "
                    "    neighbor.station_id   AS station_id, "
                    "    neighbor.name         AS name, "
                    "    neighbor.network_type AS network_type, "
                    "    neighbor.lines        AS lines"
                ).format(hops=hops)

                neighbors = session.run(
                    ripple_query,
                    station_id=affected_station_id,
                ).data()

                if not neighbors:
                    return {
                        "affected_station_id": affected_station_id,
                        "affected_station": affected_station,
                        "primary_impact_zone": [],
                        "secondary_impact_zone": [],
                        "total_affected_stations": 0,
                        "total_hops_searched": hops,
                    }

                # ── Pass 3: exact hop count for each neighbour ───────────────
                distance_query = (
                    "MATCH (center:Station {{station_id: $center_id}}) "
                    "MATCH (neighbor:Station {{station_id: $neighbor_id}}) "
                    "MATCH path = shortestPath((center)-[*1..{hops}]-(neighbor)) "
                    "RETURN length(path) AS hop_count"
                ).format(hops=hops)

                primary_impact_zone = []
                secondary_impact_zone = []

                for n in neighbors:
                    nid = n["station_id"]
                    rec = session.run(
                        distance_query,
                        center_id=affected_station_id,
                        neighbor_id=nid,
                    ).single()
                    hop_count = rec["hop_count"] if rec else hops

                    station_info = {
                        "station_id": nid,
                        "name": n["name"],
                        "network_type": n["network_type"],
                        "lines": n["lines"],
                        "hops_away": hop_count,
                    }
                    if hop_count == 1:
                        primary_impact_zone.append(station_info)
                    else:
                        secondary_impact_zone.append(station_info)

                primary_impact_zone.sort(key=lambda x: x["station_id"])
                secondary_impact_zone.sort(key=lambda x: x["station_id"])

                return {
                    "affected_station_id": affected_station_id,
                    "affected_station": affected_station,
                    "primary_impact_zone": primary_impact_zone,
                    "secondary_impact_zone": secondary_impact_zone,
                    "total_affected_stations": len(primary_impact_zone) + len(secondary_impact_zone),
                    "total_hops_searched": hops,
                }

    except Exception as e:
        return _empty_ripple_result(
            affected_station_id,
            hops,
            error=f"Error querying delay ripple: {str(e)}",
        )


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
    same-network links (METRO_LINK / RAIL_LINK segments) and INTERCHANGE_TO
    (cross-network walking transfers).

    Args:
        station_id: e.g. "MS01" or "NR01"

    Returns:
        list of dicts each containing:
          from_station_id, from_station_name, from_network,
          to_station_id, to_station_name, to_network,
          relationship_type ("METRO_LINK" / "RAIL_LINK" or "INTERCHANGE_TO"),
          travel_time_min, line (None for INTERCHANGE_TO).
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
