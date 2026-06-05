"""
Unit tests for Stage 3.4 — UI & Observability
==============================================
DoD coverage:
  1. StructuredLogger: JSON output, required fields, extra kwargs, stack_trace, levels
  2. Prometheus metrics: query_counter (Counter), query_duration (Histogram)
  3. healthz(): JSON structure, dual-DB health status, graceful error handling
  4. agent.py: progress_callback wiring, timing instrumentation, StructuredLogger use
  5. ui.py chat(): generator pattern, _TOOL_STATUS map, no time.sleep, real yields
"""

from __future__ import annotations

import inspect
import io
import json
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy dependencies before skeleton.agent is imported ─────────────────
# LLMProvider.__init__ calls _check_ollama() which tries to connect to a live
# Ollama server.  Inject stubs so the module can be imported in unit tests
# without requiring external services.  (Same pattern as test_phase_3.1 / 3.2.)
sys.modules.setdefault("skeleton.llm_provider", MagicMock(llm=MagicMock()))
sys.modules.setdefault("databases.relational.queries", MagicMock())
sys.modules.setdefault("databases.graph.queries", MagicMock())


# ═════════════════════════════════════════════════════════════════════════════
# Helper
# ═════════════════════════════════════════════════════════════════════════════

def _make_logger_with_capture():
    """
    Return (StructuredLogger, io.StringIO).

    Each call uses a UUID-based name to guarantee a fresh logger (Python's
    logging manager caches loggers by name).  Output is redirected from
    stderr to the StringIO so tests can inspect it without capsys.
    """
    from skeleton.logging_config import StructuredLogger
    sio = io.StringIO()
    name = f"test.{uuid.uuid4().hex[:8]}"
    lg = StructuredLogger(name)
    lg._logger.handlers[0].stream = sio
    return lg, sio


# ═════════════════════════════════════════════════════════════════════════════
# 1. StructuredLogger
# ═════════════════════════════════════════════════════════════════════════════

class TestStructuredLogger:
    """StructuredLogger must emit one JSON object per line with required fields."""

    def test_info_output_is_valid_json(self):
        lg, sio = _make_logger_with_capture()
        lg.info("test_event")
        data = json.loads(sio.getvalue().strip())
        assert isinstance(data, dict)

    def test_output_contains_timestamp(self):
        lg, sio = _make_logger_with_capture()
        lg.info("test_event")
        data = json.loads(sio.getvalue().strip())
        assert "timestamp" in data

    def test_output_contains_event(self):
        lg, sio = _make_logger_with_capture()
        lg.info("my_event")
        data = json.loads(sio.getvalue().strip())
        assert data["event"] == "my_event"

    def test_extra_kwargs_appear_in_output(self):
        lg, sio = _make_logger_with_capture()
        lg.info("tool_executed", tool="find_route", duration_ms=42.5, status="success")
        data = json.loads(sio.getvalue().strip())
        assert data["tool"] == "find_route"
        assert data["duration_ms"] == 42.5
        assert data["status"] == "success"

    def test_error_with_exc_includes_stack_trace(self):
        lg, sio = _make_logger_with_capture()
        try:
            raise ValueError("something broke")
        except ValueError as e:
            lg.error("tool_error", exc=e, tool="check_metro_availability")
        data = json.loads(sio.getvalue().strip())
        assert "stack_trace" in data
        assert isinstance(data["stack_trace"], str)
        assert "ValueError" in data["stack_trace"]

    def test_error_without_exc_has_no_stack_trace(self):
        lg, sio = _make_logger_with_capture()
        lg.error("simple_error", tool="find_route")
        data = json.loads(sio.getvalue().strip())
        assert "stack_trace" not in data

    def test_warning_is_valid_json(self):
        lg, sio = _make_logger_with_capture()
        lg.warning("rate_limited", tool="search_policy")
        data = json.loads(sio.getvalue().strip())
        assert data["event"] == "rate_limited"
        assert data["tool"] == "search_policy"

    def test_debug_is_valid_json(self):
        lg, sio = _make_logger_with_capture()
        lg.debug("cache_hit", key="fare:NR01:NR05:standard")
        data = json.loads(sio.getvalue().strip())
        assert data["event"] == "cache_hit"
        assert data["key"] == "fare:NR01:NR05:standard"

    def test_each_call_emits_exactly_one_line(self):
        lg, sio = _make_logger_with_capture()
        lg.info("first")
        lg.info("second")
        lg.info("third")
        lines = [ln for ln in sio.getvalue().strip().splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_stack_trace_is_nested_string_not_broken_json(self):
        """Stack trace (with embedded newlines) must not break JSON validity."""
        lg, sio = _make_logger_with_capture()
        try:
            raise RuntimeError("deep error")
        except RuntimeError as e:
            lg.error("deep_failure", exc=e)
        raw = sio.getvalue().strip()
        data = json.loads(raw)   # must not raise
        assert isinstance(data["stack_trace"], str)

    def test_timestamp_is_iso_8601(self):
        from datetime import datetime
        lg, sio = _make_logger_with_capture()
        lg.info("ts_check")
        data = json.loads(sio.getvalue().strip())
        datetime.fromisoformat(data["timestamp"])  # must not raise

    def test_two_loggers_are_independent(self):
        """Setting different names must not share output streams."""
        from skeleton.logging_config import StructuredLogger
        sio1, sio2 = io.StringIO(), io.StringIO()
        lg1 = StructuredLogger(f"test.a.{uuid.uuid4().hex[:8]}")
        lg2 = StructuredLogger(f"test.b.{uuid.uuid4().hex[:8]}")
        lg1._logger.handlers[0].stream = sio1
        lg2._logger.handlers[0].stream = sio2
        lg1.info("only_in_lg1")
        assert "only_in_lg1" in sio1.getvalue()
        assert sio2.getvalue() == ""


# ═════════════════════════════════════════════════════════════════════════════
# 2. Prometheus Metrics
# ═════════════════════════════════════════════════════════════════════════════

class TestPrometheusMetrics:
    """query_counter must be a Counter; query_duration must be a Histogram."""

    def test_query_counter_is_counter(self):
        from prometheus_client import Counter
        from skeleton.metrics import query_counter
        assert isinstance(query_counter, Counter)

    def test_query_duration_is_histogram(self):
        from prometheus_client import Histogram
        from skeleton.metrics import query_duration
        assert isinstance(query_duration, Histogram)

    def test_query_counter_accepts_tool_and_status_labels(self):
        from skeleton.metrics import query_counter
        child = query_counter.labels(tool="find_route", status="success")
        assert child is not None

    def test_query_duration_accepts_tool_label(self):
        from skeleton.metrics import query_duration
        child = query_duration.labels(tool="search_policy")
        assert child is not None

    def test_query_counter_can_be_incremented(self):
        from skeleton.metrics import query_counter
        query_counter.labels(tool="get_delay_ripple", status="success").inc()

    def test_query_duration_can_observe(self):
        from skeleton.metrics import query_duration
        query_duration.labels(tool="find_alternative_routes").observe(0.123)

    def test_query_counter_has_tool_label_name(self):
        from skeleton.metrics import query_counter
        assert "tool" in query_counter._labelnames

    def test_query_counter_has_status_label_name(self):
        from skeleton.metrics import query_counter
        assert "status" in query_counter._labelnames

    def test_query_duration_has_tool_label_name(self):
        from skeleton.metrics import query_duration
        assert "tool" in query_duration._labelnames


# ═════════════════════════════════════════════════════════════════════════════
# 3. healthz()
# ═════════════════════════════════════════════════════════════════════════════

class TestHealthz:
    """healthz() must return a valid JSON string describing DB connectivity."""

    def test_returns_string(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            result = healthz()
        assert isinstance(result, str)

    def test_return_value_is_valid_json(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert isinstance(data, dict)

    def test_json_has_status_key(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert "status" in data

    def test_json_has_databases_key(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert "databases" in data

    def test_databases_has_postgresql_key(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert "postgresql" in data["databases"]

    def test_databases_has_neo4j_key(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert "neo4j" in data["databases"]

    def test_both_healthy_returns_healthy_status(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert data["status"] == "healthy"

    def test_both_healthy_postgresql_value_is_healthy(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert data["databases"]["postgresql"] == "healthy"

    def test_both_healthy_neo4j_value_is_healthy(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"), patch("neo4j.GraphDatabase.driver"):
            data = json.loads(healthz())
        assert data["databases"]["neo4j"] == "healthy"

    def test_postgresql_failure_returns_degraded_status(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect", side_effect=Exception("Connection refused")):
            with patch("neo4j.GraphDatabase.driver"):
                data = json.loads(healthz())
        assert data["status"] == "degraded"

    def test_postgresql_failure_value_contains_unhealthy(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect", side_effect=Exception("Connection refused")):
            with patch("neo4j.GraphDatabase.driver"):
                data = json.loads(healthz())
        assert "unhealthy" in data["databases"]["postgresql"]

    def test_neo4j_failure_returns_degraded_status(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"):
            with patch("neo4j.GraphDatabase.driver", side_effect=Exception("Service unavailable")):
                data = json.loads(healthz())
        assert data["status"] == "degraded"

    def test_neo4j_failure_value_contains_unhealthy(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect"):
            with patch("neo4j.GraphDatabase.driver", side_effect=Exception("Service unavailable")):
                data = json.loads(healthz())
        assert "unhealthy" in data["databases"]["neo4j"]

    def test_both_failures_returns_degraded(self):
        from skeleton.health_check import healthz
        with patch("psycopg2.connect", side_effect=Exception("PG down")):
            with patch("neo4j.GraphDatabase.driver", side_effect=Exception("Neo4j down")):
                data = json.loads(healthz())
        assert data["status"] == "degraded"

    def test_error_message_embedded_in_unhealthy_string(self):
        """The original exception message must be in the "unhealthy: …" value."""
        from skeleton.health_check import healthz
        with patch("psycopg2.connect", side_effect=Exception("auth failed")):
            with patch("neo4j.GraphDatabase.driver"):
                data = json.loads(healthz())
        assert "auth failed" in data["databases"]["postgresql"]

    def test_healthz_never_raises(self):
        """DB errors must be caught; healthz() must not propagate exceptions."""
        from skeleton.health_check import healthz
        with patch("psycopg2.connect", side_effect=Exception("bang")):
            with patch("neo4j.GraphDatabase.driver", side_effect=Exception("boom")):
                try:
                    healthz()
                except Exception as exc:
                    pytest.fail(f"healthz() raised unexpectedly: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# 4. Agent — progress_callback wiring
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentProgressCallback:
    """progress_callback must be called once per executed tool."""

    def test_run_method_has_progress_callback_param(self):
        from skeleton.agent import TransitFlowAgent
        sig = inspect.signature(TransitFlowAgent.run)
        assert "progress_callback" in sig.parameters

    def test_run_agent_function_has_progress_callback_param(self):
        from skeleton.agent import run_agent
        sig = inspect.signature(run_agent)
        assert "progress_callback" in sig.parameters

    def test_progress_callback_defaults_to_none(self):
        from skeleton.agent import TransitFlowAgent
        param = inspect.signature(TransitFlowAgent.run).parameters["progress_callback"]
        assert param.default is None

    def test_callback_called_with_tool_name_string(self):
        """Callback receives the tool name (e.g. 'search_policy') as a string."""
        mock_db    = MagicMock()
        mock_graph = MagicMock()
        mock_db.query_policy_vector_search.return_value = []
        mock_db.query_user_profile.return_value = None

        from skeleton.agent import TransitFlowAgent
        agent = TransitFlowAgent(db_service=mock_db, graph_service=mock_graph)
        called_with: list[str] = []

        tool_json = '{"tool_calls": [{"name": "search_policy", "params": {"query": "refund"}}]}'
        with patch("skeleton.agent.llm") as mock_llm:
            mock_llm.get_chat_provider.return_value = "gemini"
            mock_llm.chat.side_effect = [tool_json, "Refund answer."]
            mock_llm.embed.return_value = [0.0] * 768

            agent.run("What is the refund policy?", [], progress_callback=called_with.append)

        assert "search_policy" in called_with
        assert all(isinstance(v, str) for v in called_with)

    def test_callback_not_called_when_no_tools_selected(self):
        """Conversational queries (no DB tools) must not fire the callback."""
        mock_db    = MagicMock()
        mock_graph = MagicMock()
        mock_db.query_user_profile.return_value = None

        from skeleton.agent import TransitFlowAgent
        agent = TransitFlowAgent(db_service=mock_db, graph_service=mock_graph)
        called_with: list[str] = []

        with patch("skeleton.agent.llm") as mock_llm:
            mock_llm.get_chat_provider.return_value = "gemini"
            mock_llm.chat.side_effect = ['{"tool_calls": []}', "Hello!"]

            agent.run("Hello", [], progress_callback=called_with.append)

        assert called_with == []

    def test_callback_called_once_per_tool_for_multi_tool_query(self):
        """With two tools selected, callback is called exactly twice (one each)."""
        mock_db    = MagicMock()
        mock_graph = MagicMock()
        mock_db.query_policy_vector_search.return_value = []
        mock_db.query_national_rail_availability.return_value = []
        mock_db.query_user_profile.return_value = None

        from skeleton.agent import TransitFlowAgent
        agent = TransitFlowAgent(db_service=mock_db, graph_service=mock_graph)
        called_with: list[str] = []

        two_tools = json.dumps({"tool_calls": [
            {"name": "search_policy",
             "params": {"query": "delay compensation"}},
            {"name": "check_national_rail_availability",
             "params": {"origin_id": "NR01", "destination_id": "NR05"}},
        ]})
        with patch("skeleton.agent.llm") as mock_llm:
            mock_llm.get_chat_provider.return_value = "gemini"
            mock_llm.chat.side_effect = [two_tools, "Combined answer."]
            mock_llm.embed.return_value = [0.0] * 768

            agent.run("Delay policy and NR01-NR05 trains?", [], progress_callback=called_with.append)

        assert len(called_with) == 2
        assert "search_policy" in called_with
        assert "check_national_rail_availability" in called_with


# ═════════════════════════════════════════════════════════════════════════════
# 5. Agent source — StructuredLogger + timing instrumentation
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentInstrumentationSource:
    """
    Static source inspection: agent.py must integrate StructuredLogger and
    measure tool duration.
    """

    @pytest.fixture(scope="class")
    def agent_src(self):
        import skeleton.agent as _m
        return inspect.getsource(_m)

    def test_imports_structured_logger(self, agent_src):
        assert "StructuredLogger" in agent_src

    def test_has_module_level_logger(self, agent_src):
        assert "_logger" in agent_src

    def test_execute_tool_measures_duration(self, agent_src):
        assert "perf_counter" in agent_src

    def test_execute_tool_logs_duration_ms(self, agent_src):
        assert "duration_ms" in agent_src

    def test_execute_tool_records_prometheus_metrics(self, agent_src):
        assert "query_counter" in agent_src

    def test_progress_callback_wiring_present(self, agent_src):
        assert "progress_callback" in agent_src


# ═════════════════════════════════════════════════════════════════════════════
# 6. UI chat() — generator pattern & tool status map
# ═════════════════════════════════════════════════════════════════════════════

class TestUIChatGenerator:
    """chat() must be a generator; _TOOL_STATUS must cover expected tools."""

    def test_chat_is_generator_function(self):
        from skeleton.ui import chat
        assert inspect.isgeneratorfunction(chat), (
            "skeleton/ui.py chat() must use `yield` (generator function)"
        )

    def test_chat_source_has_no_time_sleep(self):
        import skeleton.ui as _ui
        src = inspect.getsource(_ui.chat)
        assert "time.sleep" not in src

    def test_tool_status_map_exists(self):
        from skeleton.ui import _TOOL_STATUS
        assert isinstance(_TOOL_STATUS, dict)

    def test_tool_status_map_has_at_least_10_entries(self):
        from skeleton.ui import _TOOL_STATUS
        assert len(_TOOL_STATUS) >= 10

    def test_tool_status_map_covers_search_policy(self):
        from skeleton.ui import _TOOL_STATUS
        assert "search_policy" in _TOOL_STATUS

    def test_tool_status_map_covers_find_route(self):
        from skeleton.ui import _TOOL_STATUS
        assert "find_route" in _TOOL_STATUS

    def test_tool_status_map_covers_check_national_rail_availability(self):
        from skeleton.ui import _TOOL_STATUS
        assert "check_national_rail_availability" in _TOOL_STATUS

    def test_tool_status_map_covers_check_metro_availability(self):
        from skeleton.ui import _TOOL_STATUS
        assert "check_metro_availability" in _TOOL_STATUS

    def test_tool_status_map_covers_make_booking(self):
        from skeleton.ui import _TOOL_STATUS
        assert "make_booking" in _TOOL_STATUS

    def test_all_status_messages_contain_progress_emoji(self):
        """Every status message must contain 🔄 to signal ongoing work."""
        from skeleton.ui import _TOOL_STATUS
        for tool, msg in _TOOL_STATUS.items():
            assert "🔄" in msg, f"Status for '{tool}' is missing 🔄"

    def test_empty_message_yields_nothing(self):
        from skeleton.ui import chat
        results = list(chat("   ", [], [], False, None))
        assert results == []

    def test_first_yield_contains_user_message_immediately(self):
        """
        The very first yield must already show the user message — it arrives
        before the agent thread finishes so the UI unfreezes right away.
        """
        from skeleton.ui import chat
        with patch("skeleton.ui.run_agent") as mock_ra:
            mock_ra.return_value = ("Answer.", [])
            results = list(chat("hello world", [], [], False, None))

        first_history = results[0][0]
        user_turns = [m for m in first_history if m.get("role") == "user"]
        assert any("hello world" in m["content"] for m in user_turns)

    def test_first_yield_shows_thinking_placeholder(self):
        """First yield assistant message must be a 🔄 progress string."""
        from skeleton.ui import chat
        with patch("skeleton.ui.run_agent") as mock_ra:
            mock_ra.return_value = ("Answer.", [])
            results = list(chat("hello world", [], [], False, None))

        first_history = results[0][0]
        assistant_turns = [m for m in first_history if m.get("role") == "assistant"]
        assert any("🔄" in m["content"] for m in assistant_turns)

    def test_final_yield_contains_real_answer(self):
        """After the agent finishes, last yield must show the actual answer."""
        from skeleton.ui import chat
        with patch("skeleton.ui.run_agent") as mock_ra:
            mock_ra.return_value = ("The real answer.", [])
            results = list(chat("test query", [], [], False, None))

        last_history = results[-1][0]
        assistant_turns = [m for m in last_history if m.get("role") == "assistant"]
        assert any("The real answer." in m["content"] for m in assistant_turns)

    def test_yields_more_than_one_time_for_tool_query(self):
        """
        For a query with one tool call, we expect at least 2 yields:
        the initial thinking placeholder + the final answer.
        """
        from skeleton.ui import chat
        with patch("skeleton.ui.run_agent") as mock_ra:
            mock_ra.return_value = ("Answer.", [])
            results = list(chat("What trains run?", [], [], False, None))

        assert len(results) >= 2


if __name__ == "__main__":
    print("Run with: pytest tests/unit/test_phase_3.4_ui_observability.py -v")
