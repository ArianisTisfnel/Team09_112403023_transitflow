"""
Unit tests for the Task 6 §C pgvector tool router.

Covers:
  - query_tool_candidates(): SQL shape, return shape, ordering passthrough
  - _embedding_route_candidates(): disabled by default; threshold filtering when on
  - _router_params_for(): best-effort param inference per tool
"""

from unittest.mock import MagicMock, patch

import skeleton.config as cfg
from databases.relational.queries import query_tool_candidates
from skeleton.agent import _embedding_route_candidates, _router_params_for


# ── query_tool_candidates ─────────────────────────────────────────────────────

def _mock_connect(fetchall_value):
    mock_connect = patch("databases.relational.queries._connect").start()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = fetchall_value
    return mock_connect, mock_cursor


def test_query_tool_candidates_shape_and_query():
    rows = [{"name": "search_policy", "similarity": 0.81},
            {"name": "find_route", "similarity": 0.42}]
    _, mock_cursor = _mock_connect(rows)
    try:
        result = query_tool_candidates([0.0] * 768, top_k=2)
    finally:
        patch.stopall()
    assert result == [
        {"name": "search_policy", "similarity": 0.81},
        {"name": "find_route", "similarity": 0.42},
    ]
    sql, params = mock_cursor.execute.call_args[0]
    assert "tool_descriptions" in sql
    assert params[-1] == 2  # top_k is the last bind param


def test_query_tool_candidates_empty():
    _mock_connect([])
    try:
        assert query_tool_candidates([0.0] * 768, top_k=4) == []
    finally:
        patch.stopall()


# ── _embedding_route_candidates ───────────────────────────────────────────────

def test_router_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(cfg, "USE_EMBEDDING_ROUTER", False)
    db = MagicMock()
    # Must short-circuit without touching the DB or LLM.
    assert _embedding_route_candidates(db, "can I get a refund?") == []
    db.query_tool_candidates.assert_not_called()


def test_router_enabled_filters_by_threshold(monkeypatch):
    monkeypatch.setattr(cfg, "USE_EMBEDDING_ROUTER", True)
    monkeypatch.setattr(cfg, "TOOL_ROUTER_TOP_K", 4)
    monkeypatch.setattr(cfg, "TOOL_ROUTER_THRESHOLD", 0.4)
    monkeypatch.setattr("skeleton.agent.llm.embed", lambda _t: [0.0] * 768)
    db = MagicMock()
    db.query_tool_candidates.return_value = [
        {"name": "search_policy", "similarity": 0.80},
        {"name": "find_route", "similarity": 0.30},  # below threshold → dropped
    ]
    out = _embedding_route_candidates(db, "refund for a delay?")
    assert [c["name"] for c in out] == ["search_policy"]


def test_router_swallows_errors(monkeypatch):
    monkeypatch.setattr(cfg, "USE_EMBEDDING_ROUTER", True)
    def _boom(_t):
        raise RuntimeError("embed down")
    monkeypatch.setattr("skeleton.agent.llm.embed", _boom)
    assert _embedding_route_candidates(MagicMock(), "anything") == []


# ── _router_params_for ────────────────────────────────────────────────────────

def test_params_search_policy_uses_full_message():
    assert _router_params_for("search_policy", "refund?", "a@b.com", [], "refund?") == {"query": "refund?"}


def test_params_user_bookings_requires_login():
    assert _router_params_for("get_user_bookings", "my trips", "a@b.com", [], "my trips") == {}
    assert _router_params_for("get_user_bookings", "my trips", None, [], "my trips") is None


def test_params_find_route_with_two_stations():
    p = _router_params_for("find_route", "MS01 to MS09", None, ["MS01", "MS09"], "ms01 to ms09")
    assert p == {"origin_id": "MS01", "destination_id": "MS09", "optimise_by": "time"}


def test_params_find_route_cost_optimise():
    p = _router_params_for("find_route", "cheapest NR01 to NR05", None, ["NR01", "NR05"], "cheapest nr01 to nr05")
    assert p["optimise_by"] == "cost"


def test_params_none_for_tools_needing_unknown_ids():
    # make_booking needs schedule_id/seat_id we cannot infer → None (leave to LLM)
    assert _router_params_for("make_booking", "book me a seat", "a@b.com", ["NR01", "NR05"], "book me a seat") is None
