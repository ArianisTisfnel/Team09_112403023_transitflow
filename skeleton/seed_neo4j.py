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
    """Create :Station nodes for the 20 metro stations (MS01–MS20)."""
    for station in stations:
        session.run(
            """
            MERGE (s:Station {station_id: $station_id})
            SET s.name = $name,
                s.network_type = $network_type,
                s.lines = $lines
            """,
            station_id=station["station_id"],
            name=station["name"],
            network_type="metro",
            lines=station["lines"],
        )
    print(f"  Seeded {len(stations)} metro :Station nodes")


def seed_national_rail_stations(session, stations):
    """Create :Station nodes for the 10 national rail stations (NR01–NR10)."""
    for station in stations:
        session.run(
            """
            MERGE (s:Station {station_id: $station_id})
            SET s.name = $name,
                s.network_type = $network_type,
                s.lines = $lines
            """,
            station_id=station["station_id"],
            name=station["name"],
            network_type="national_rail",
            lines=station["lines"],
        )
    print(f"  Seeded {len(stations)} national rail :Station nodes")


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        seed_metro_stations(session, metro_stations)
        seed_national_rail_stations(session, rail_stations)

        # TODO (B.2): seed CONNECTS_TO relationships for metro and national rail
        # TODO (B.3): seed INTERCHANGE relationships between metro and rail

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
