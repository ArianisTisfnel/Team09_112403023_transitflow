"""
Unit tests for Stage 3.1 — Global Exception Handling Layer

DoD coverage:
  - TransitFlowException base class has .message and .error_code attributes
  - DatabaseException, ValidationException, RouteNotFoundException, SeatUnavailableException
    all inherit from TransitFlowException and carry message/error_code
  - error_handler catches TransitFlowException → {"success": False, "error": {"message": ..., "code": ...}}
  - error_handler catches unknown Exception → {"success": False, "error": {"code": "INTERNAL_ERROR"}}
  - error_handler preserves __name__ and __doc__ via functools.wraps
  - Normal return values pass through the decorator unchanged
  - _execute_tool is decorated with @error_handler (RouteNotFoundException → structured JSON, no traceback)
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy dependencies before agent.py is imported ─────────────────────
# LLMProvider.__init__ calls _check_ollama() which tries to connect to a live
# Ollama server; database modules require live PostgreSQL/Neo4j.
# Inject stubs so the import itself succeeds without external services.
sys.modules.setdefault("skeleton.llm_provider", MagicMock(llm=MagicMock()))
sys.modules.setdefault("databases.relational.queries", MagicMock())
sys.modules.setdefault("databases.graph.queries", MagicMock())

from skeleton.exceptions import (
    DatabaseException,
    RouteNotFoundException,
    SeatUnavailableException,
    TransitFlowException,
    ValidationException,
)
from skeleton.agent import _default_agent, error_handler


# ═════════════════════════════════════════════════════════════════════════════
# Exception hierarchy — skeleton/exceptions.py
# ═════════════════════════════════════════════════════════════════════════════

class TestTransitFlowException:
    def test_message_attribute_stored(self):
        """TransitFlowException must expose .message (used by error_handler)."""
        e = TransitFlowException("something went wrong", "ERR_001")
        assert e.message == "something went wrong"

    def test_error_code_attribute_stored(self):
        e = TransitFlowException("oops", "ERR_XYZ")
        assert e.error_code == "ERR_XYZ"

    def test_default_error_code_is_empty_string(self):
        e = TransitFlowException("no code given")
        assert e.error_code == ""

    def test_is_subclass_of_exception(self):
        assert issubclass(TransitFlowException, Exception)

    def test_str_contains_message(self):
        e = TransitFlowException("my message", "CODE")
        assert "my message" in str(e)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(TransitFlowException) as exc_info:
            raise TransitFlowException("raised", "RAISED_CODE")
        assert exc_info.value.message == "raised"
        assert exc_info.value.error_code == "RAISED_CODE"


class TestExceptionSubclasses:
    @pytest.mark.parametrize("exc_class", [
        DatabaseException,
        ValidationException,
        RouteNotFoundException,
        SeatUnavailableException,
    ])
    def test_is_subclass_of_transit_flow_exception(self, exc_class):
        assert issubclass(exc_class, TransitFlowException)

    @pytest.mark.parametrize("exc_class", [
        DatabaseException,
        ValidationException,
        RouteNotFoundException,
        SeatUnavailableException,
    ])
    def test_message_and_code_inherited(self, exc_class):
        e = exc_class("test error", "TEST_CODE")
        assert e.message == "test error"
        assert e.error_code == "TEST_CODE"

    def test_route_not_found_catchable_as_transit_flow(self):
        with pytest.raises(TransitFlowException):
            raise RouteNotFoundException("No route found", "ROUTE_NOT_FOUND")

    def test_database_exception_catchable_as_transit_flow(self):
        with pytest.raises(TransitFlowException):
            raise DatabaseException("DB down", "DB_ERROR")

    def test_validation_exception_catchable_as_transit_flow(self):
        with pytest.raises(TransitFlowException):
            raise ValidationException("bad input", "INVALID_INPUT")

    def test_seat_unavailable_catchable_as_transit_flow(self):
        with pytest.raises(TransitFlowException):
            raise SeatUnavailableException("seat taken", "SEAT_TAKEN")


# ═════════════════════════════════════════════════════════════════════════════
# error_handler decorator — skeleton/agent.py
# ═════════════════════════════════════════════════════════════════════════════

def _wrap(side_effect=None, return_value="ok"):
    """Helper: create and decorate a tiny function for decorator tests."""
    def inner():
        """original docstring"""
        if side_effect is not None:
            raise side_effect
        return return_value
    inner.__name__ = "inner"
    return error_handler(inner)


class TestErrorHandlerNormalPath:
    def test_non_exception_return_passes_through(self):
        """When no exception is raised the return value must be unchanged."""
        fn = _wrap(return_value="expected_value")
        assert fn() == "expected_value"

    def test_non_exception_none_return_passes_through(self):
        fn = _wrap(return_value=None)
        assert fn() is None


class TestErrorHandlerTransitFlowException:
    def test_success_false_in_response(self):
        fn = _wrap(RouteNotFoundException("No route A→B", "ROUTE_NOT_FOUND"))
        result = json.loads(fn())
        assert result["success"] is False

    def test_error_message_preserved(self):
        fn = _wrap(RouteNotFoundException("No route A→B", "ROUTE_NOT_FOUND"))
        result = json.loads(fn())
        assert result["error"]["message"] == "No route A→B"

    def test_error_code_preserved(self):
        fn = _wrap(RouteNotFoundException("No route A→B", "ROUTE_NOT_FOUND"))
        result = json.loads(fn())
        assert result["error"]["code"] == "ROUTE_NOT_FOUND"

    def test_no_traceback_in_output(self):
        """DoD: frontend must receive JSON, NOT a Python traceback."""
        fn = _wrap(RouteNotFoundException("No route", "ROUTE_NOT_FOUND"))
        raw = fn()
        assert "Traceback" not in raw
        assert "File " not in raw
        assert "line " not in raw

    def test_output_is_valid_json(self):
        fn = _wrap(RouteNotFoundException("err", "CODE"))
        raw = fn()
        json.loads(raw)  # must not raise

    def test_database_exception_code_in_response(self):
        fn = _wrap(DatabaseException("connection refused", "DB_CONN_FAIL"))
        result = json.loads(fn())
        assert result["error"]["code"] == "DB_CONN_FAIL"

    def test_validation_exception_code_in_response(self):
        fn = _wrap(ValidationException("invalid date", "INVALID_DATE"))
        result = json.loads(fn())
        assert result["error"]["code"] == "INVALID_DATE"

    def test_seat_unavailable_exception_code_in_response(self):
        fn = _wrap(SeatUnavailableException("seat A1 taken", "SEAT_UNAVAILABLE"))
        result = json.loads(fn())
        assert result["error"]["code"] == "SEAT_UNAVAILABLE"


class TestErrorHandlerUnknownException:
    def test_success_false_for_unknown_exception(self):
        fn = _wrap(RuntimeError("unexpected crash"))
        result = json.loads(fn())
        assert result["success"] is False

    def test_internal_error_code_for_unknown_exception(self):
        fn = _wrap(RuntimeError("unexpected crash"))
        result = json.loads(fn())
        assert result["error"]["code"] == "INTERNAL_ERROR"

    def test_no_traceback_in_output_for_unknown_exception(self):
        fn = _wrap(RuntimeError("crash"))
        raw = fn()
        assert "Traceback" not in raw

    def test_output_is_valid_json_for_unknown_exception(self):
        fn = _wrap(RuntimeError("crash"))
        raw = fn()
        json.loads(raw)  # must not raise


class TestErrorHandlerFunctools:
    def test_preserves_function_name(self):
        def my_func():
            """doc"""
            return "x"
        wrapped = error_handler(my_func)
        assert wrapped.__name__ == "my_func"

    def test_preserves_function_docstring(self):
        def my_func():
            """original docstring"""
            return "x"
        wrapped = error_handler(my_func)
        assert wrapped.__doc__ == "original docstring"

    def test_wrapped_attribute_set(self):
        """functools.wraps sets __wrapped__ — confirms decorator was applied."""
        def my_func():
            return "x"
        wrapped = error_handler(my_func)
        assert wrapped.__wrapped__ is my_func


# ═════════════════════════════════════════════════════════════════════════════
# _execute_tool integration — @error_handler actually applied
# ═════════════════════════════════════════════════════════════════════════════

class TestExecuteToolWithErrorHandler:
    """
    Confirm @error_handler is live on TransitFlowAgent._execute_tool.
    We patch the service object methods on _default_agent to raise exceptions;
    _execute_tool must return structured JSON, never crash.

    Stage 3.2 note: _execute_tool is now a method on TransitFlowAgent.
    Patch targets moved from module-level names to service object attributes
    (self.db.* / self.graph.*) so we use patch.object() on the service instances.
    """

    def test_execute_tool_has_wrapped_attribute(self):
        """@error_handler via functools.wraps sets __wrapped__ on _execute_tool."""
        assert hasattr(_default_agent._execute_tool, "__wrapped__"), (
            "_execute_tool lacks __wrapped__; @error_handler may not be applied"
        )

    def test_route_not_found_returns_structured_json(self):
        """DoD: RouteNotFoundException raised inside find_route → JSON with error_code."""
        exc = RouteNotFoundException("No route MS01→MS20", "ROUTE_NOT_FOUND")
        with patch.object(_default_agent.graph, "query_shortest_route", side_effect=exc):
            raw = _default_agent._execute_tool(
                "find_route",
                {"origin_id": "MS01", "destination_id": "MS20"},
            )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "ROUTE_NOT_FOUND"

    def test_route_not_found_no_traceback_in_output(self):
        """DoD: output must be JSON, not a Python traceback string."""
        exc = RouteNotFoundException("No route", "ROUTE_NOT_FOUND")
        with patch.object(_default_agent.graph, "query_shortest_route", side_effect=exc):
            raw = _default_agent._execute_tool(
                "find_route",
                {"origin_id": "MS01", "destination_id": "MS20"},
            )
        assert "Traceback" not in raw
        assert "File " not in raw

    def test_database_exception_in_availability_check(self):
        """DatabaseException from a query function → structured error JSON."""
        exc = DatabaseException("DB connection lost", "DB_ERROR")
        with patch.object(_default_agent.db, "query_national_rail_availability", side_effect=exc):
            raw = _default_agent._execute_tool(
                "check_national_rail_availability",
                {"origin_id": "NR01", "destination_id": "NR05"},
            )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "DB_ERROR"

    def test_unexpected_runtime_error_returns_internal_error(self):
        """Unknown RuntimeError → INTERNAL_ERROR code, no crash."""
        with patch.object(_default_agent.db, "query_metro_schedules", side_effect=RuntimeError("crash")):
            raw = _default_agent._execute_tool(
                "check_metro_availability",
                {"origin_id": "MS01", "destination_id": "MS09"},
            )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "INTERNAL_ERROR"

    def test_unexpected_error_no_traceback_in_output(self):
        with patch.object(_default_agent.db, "query_metro_schedules", side_effect=RuntimeError("crash")):
            raw = _default_agent._execute_tool(
                "check_metro_availability",
                {"origin_id": "MS01", "destination_id": "MS09"},
            )
        assert "Traceback" not in raw

    def test_all_tool_outputs_are_valid_json(self):
        """Any exception path must still produce parseable JSON."""
        exc = SeatUnavailableException("no seats", "SEAT_UNAVAILABLE")
        with patch.object(_default_agent.db, "query_available_seats", side_effect=exc):
            raw = _default_agent._execute_tool(
                "get_available_seats",
                {"schedule_id": "NR_SCH01", "travel_date": "2026-06-01", "fare_class": "standard"},
            )
        json.loads(raw)  # must not raise


if __name__ == "__main__":
    tests = [
        # Exception hierarchy
        TestTransitFlowException().test_message_attribute_stored,
        TestTransitFlowException().test_error_code_attribute_stored,
        TestTransitFlowException().test_default_error_code_is_empty_string,
        TestTransitFlowException().test_is_subclass_of_exception,
        # error_handler
        TestErrorHandlerNormalPath().test_non_exception_return_passes_through,
        TestErrorHandlerTransitFlowException().test_success_false_in_response,
        TestErrorHandlerTransitFlowException().test_error_message_preserved,
        TestErrorHandlerTransitFlowException().test_error_code_preserved,
        TestErrorHandlerTransitFlowException().test_no_traceback_in_output,
        TestErrorHandlerUnknownException().test_internal_error_code_for_unknown_exception,
        TestErrorHandlerFunctools().test_preserves_function_name,
        TestErrorHandlerFunctools().test_wrapped_attribute_set,
        # _execute_tool integration (Stage 3.2: now an instance method on TransitFlowAgent)
        TestExecuteToolWithErrorHandler().test_execute_tool_has_wrapped_attribute,
    ]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\n✓ {len(tests)} smoke tests passed")
