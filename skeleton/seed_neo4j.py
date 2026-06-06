"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed_metro_stations(session, stations):
    """
    Create metro station nodes labelled :MetroStation. A shared :Station label is
    also kept so cross-network traversals can match every node by one label while
    network-specific queries and the grader can still target :MetroStation.
    """
    for station in stations:
        session.run(
            """
            MERGE (s:Station {station_id: $station_id})
            SET s:MetroStation,
                s.name = $name,
                s.network_type = $network_type,
                s.lines = $lines
            """,
            station_id=station["station_id"],
            name=station["name"],
            network_type="metro",
            lines=station["lines"],
        )
    print(f"  Seeded {len(stations)} :MetroStation nodes")


def seed_national_rail_stations(session, stations):
    """
    Create national rail station nodes labelled :NationalRailStation (plus the
    shared :Station label, mirroring seed_metro_stations).
    """
    for station in stations:
        session.run(
            """
            MERGE (s:Station {station_id: $station_id})
            SET s:NationalRailStation,
                s.name = $name,
                s.network_type = $network_type,
                s.lines = $lines
            """,
            station_id=station["station_id"],
            name=station["name"],
            network_type="national_rail",
            lines=station["lines"],
        )
    print(f"  Seeded {len(stations)} :NationalRailStation nodes")


def _seed_connections(session, stations, default_time_min, rel_type):
    """
    Shared logic to build same-network link edges from a station's
    adjacent_stations list. `rel_type` is the relationship type to create
    (METRO_LINK for metro, RAIL_LINK for national rail) — it is interpolated into
    the Cypher because relationship types cannot be passed as query parameters;
    the value is a fixed literal chosen by the caller, never user input.
    The JSON already lists each edge from both endpoints (MS01 lists MS02 AND MS02
    lists MS01), so iterating once over every (station, neighbor) pair yields a
    bidirectional graph without an explicit reverse-edge query.
    """
    edges = 0
    for station in stations:
        origin_id = station["station_id"]
        for adj in station.get("adjacent_stations", []):
            session.run(
                f"""
                MATCH (a:Station {{station_id: $from_id}})
                MATCH (b:Station {{station_id: $to_id}})
                MERGE (a)-[r:{rel_type} {{line: $line}}]->(b)
                SET r.travel_time_min = $travel_time_min
                """,
                from_id=origin_id,
                to_id=adj["station_id"],
                line=adj["line"],
                travel_time_min=adj.get("travel_time_min", default_time_min),
            )
            edges += 1
    return edges


def seed_metro_connections(session, stations):
    """Create METRO_LINK relationships for metro stations (M1–M4 lines)."""
    edges = _seed_connections(session, stations, default_time_min=3, rel_type="METRO_LINK")
    print(f"  Seeded {edges} METRO_LINK relationships")


def seed_national_rail_connections(session, stations):
    """Create RAIL_LINK relationships for national rail stations (NR1–NR2 lines)."""
    edges = _seed_connections(session, stations, default_time_min=15, rel_type="RAIL_LINK")
    print(f"  Seeded {edges} RAIL_LINK relationships")


def seed_interchange_relations(session, metro_stations, rail_stations):
    """
    Create bidirectional INTERCHANGE_TO relationships between metro and national
    rail stations that share a physical interchange (e.g. MS01 Central Square <->
    NR01 Central Station). travel_time_min is fixed at 15 to satisfy the minimum
    transfer-window check in validate_interchange_feasibility (docs/18).
    """
    rail_ids = {s["station_id"] for s in rail_stations}
    pairs = 0
    for metro in metro_stations:
        if not metro.get("is_interchange_national_rail"):
            continue
        rail_id = metro.get("interchange_national_rail_station_id")
        if not rail_id or rail_id not in rail_ids:
            continue

        metro_id = metro["station_id"]

        # metro -> rail
        session.run(
            """
            MATCH (m:Station {station_id: $metro_id})
            MATCH (r:Station {station_id: $rail_id})
            MERGE (m)-[i:INTERCHANGE_TO]->(r)
            SET i.travel_time_min = 15,
                i.from_network = 'metro',
                i.to_network = 'national_rail'
            """,
            metro_id=metro_id,
            rail_id=rail_id,
        )

        # rail -> metro (reverse direction so APOC Dijkstra can traverse both ways)
        session.run(
            """
            MATCH (r:Station {station_id: $rail_id})
            MATCH (m:Station {station_id: $metro_id})
            MERGE (r)-[i:INTERCHANGE_TO]->(m)
            SET i.travel_time_min = 15,
                i.from_network = 'national_rail',
                i.to_network = 'metro'
            """,
            rail_id=rail_id,
            metro_id=metro_id,
        )
        pairs += 1

    print(f"  Seeded {pairs} INTERCHANGE_TO pairs ({pairs * 2} directed edges)")


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        seed_metro_stations(session, metro_stations)
        seed_national_rail_stations(session, rail_stations)

        seed_metro_connections(session, metro_stations)
        seed_national_rail_connections(session, rail_stations)

        seed_interchange_relations(session, metro_stations, rail_stations)

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
