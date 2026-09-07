"""Service health -- /health.

Deliberately outside /api: it is about the service, not the domain, and the
compose healthcheck calls it.

The database is a hard dependency, so a database failure is a 503. Ollama is
a soft one -- goals CRUD works perfectly well without a model, and only the
four agentic endpoints do not -- so an absent Ollama is reported honestly in
the body while the status stays 200.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..ai import client as ollama
from ..db import database_is_reachable

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    db_ok, db_error = database_is_reachable()
    ollama_status = ollama.ping()

    body = {
        "service": "lehoalong-backend",
        "feature": "Goals and Budgeting",
        "status": "ok" if db_ok else "degraded",
        "database": {"reachable": db_ok, "detail": db_error},
        "ollama": ollama_status,
    }
    return jsonify(body), (200 if db_ok else 503)
