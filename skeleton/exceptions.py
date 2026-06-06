"""
TransitFlow — custom exception hierarchy (Stage 3.1).

A small hierarchy under TransitFlowException lets the agent's @error_handler
turn domain failures into structured JSON ({"success": False, "error": {...}})
instead of leaking a Python traceback to the UI. Every exception carries a
human-readable .message and a machine-readable .error_code.
"""

# TASK 6 EXTENSION (Stage 3 robustness layer): structured exception hierarchy. See TASK6.md §B.


class TransitFlowException(Exception):
    """Base class for all TransitFlow domain errors."""

    def __init__(self, message: str, error_code: str = ""):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class DatabaseException(TransitFlowException):
    """Database operation failure (connection, query, transaction)."""
    pass


class ValidationException(TransitFlowException):
    """Input validation failure (bad station id, malformed date, etc.)."""
    pass


class RouteNotFoundException(TransitFlowException):
    """No route found between the requested stations."""
    pass


class SeatUnavailableException(TransitFlowException):
    """Requested seat is not available."""
    pass
