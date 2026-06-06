"""
Prometheus metrics for TransitFlow.

Exposes two instruments:
  transitflow_queries_total            Counter   (labels: tool, status)
  transitflow_query_duration_seconds   Histogram (labels: tool)

Import and use:
    from skeleton.metrics import query_counter, query_duration
    query_counter.labels(tool="find_route", status="success").inc()
    query_duration.labels(tool="find_route").observe(elapsed_seconds)
"""
# TASK 6 EXTENSION (Stage 3 robustness layer): Prometheus query metrics. See TASK6.md §B.
from __future__ import annotations

from prometheus_client import Counter, Histogram

query_counter: Counter = Counter(
    "transitflow_queries_total",
    "Total number of tool queries executed",
    ["tool", "status"],   # status: "success" | "error"
)

query_duration: Histogram = Histogram(
    "transitflow_query_duration_seconds",
    "Latency of individual tool queries in seconds",
    ["tool"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
