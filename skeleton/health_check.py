"""
Health check for TransitFlow — probes connectivity to both databases.

Usage:
    from skeleton.health_check import healthz
    print(healthz())
"""
# TASK 6 EXTENSION (Stage 3 robustness layer): database health probe. See TASK6.md §B.
from __future__ import annotations

import json

from skeleton.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, PG_DSN


def healthz() -> str:
    """
    Probe PostgreSQL and Neo4j with a lightweight connectivity test.

    Returns a JSON string, e.g.:
        {"status": "healthy", "databases": {"postgresql": "healthy", "neo4j": "healthy"}}
    or, when one service is down:
        {"status": "degraded", "databases": {"postgresql": "healthy", "neo4j": "unhealthy: ..."}}
    """
    results: dict[str, str] = {}

    # ── PostgreSQL ──────────────────────────────────────────────────────────────
    try:
        import psycopg2
        conn = psycopg2.connect(PG_DSN, connect_timeout=5)
        conn.close()
        results["postgresql"] = "healthy"
    except Exception as exc:
        results["postgresql"] = f"unhealthy: {exc}"

    # ── Neo4j ───────────────────────────────────────────────────────────────────
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        results["neo4j"] = "healthy"
    except Exception as exc:
        results["neo4j"] = f"unhealthy: {exc}"

    overall = "healthy" if all(v == "healthy" for v in results.values()) else "degraded"
    return json.dumps({"status": overall, "databases": results}, indent=2)
