"""API error types and the handlers that turn them into JSON.

Every failure leaving this service is JSON with the same shape, so the
frontend never has to guess whether it is parsing an object or an HTML error
page:

    {"error": "human readable message", "details": ["optional", "specifics"]}
"""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """An error with a deliberate HTTP status code.

    Raised by the service layer, caught by the handler registered below.
    """

    status_code = 500

    def __init__(self, message: str, *, status_code: int | None = None, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict:
        payload: dict = {"error": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NotFound(ApiError):
    """The addressed resource does not exist -- 404."""

    status_code = 404


class ValidationFailed(ApiError):
    """The request body or query string is unusable -- 400.

    Carries every problem found, not just the first, so a form can show all
    of its errors in one round trip.
    """

    status_code = 400

    def __init__(self, details: list[str], message: str = "Validation failed"):
        super().__init__(message, details=details)


class ServiceUnavailable(ApiError):
    """A dependency this endpoint needs is down -- 503.

    Used for Ollama being unreachable or the configured model not being
    pulled. The distinction between those two is in the message.
    """

    status_code = 503


def register_error_handlers(app: Flask) -> None:
    """Attach JSON error handlers to the app."""

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        # Covers 404 on an unknown route, 405 on a wrong method, and the 400
        # Werkzeug raises for a malformed JSON body.
        return jsonify({"error": exc.description or exc.name}), exc.code or 500

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        # Log the real cause but do not leak internals to the client.
        app.logger.exception("unhandled error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500
