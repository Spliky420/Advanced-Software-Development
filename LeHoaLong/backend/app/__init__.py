"""Application factory for the Goals & Budgeting backend.

`create_app()` builds a fully wired Flask app with no import-time side
effects, so a test can stand up an app against a temporary database without
touching the real one, and gunicorn can build the same app from wsgi.py.
"""

from __future__ import annotations

from config import Config
from flask import Flask, request

from .db import close_db
from .errors import register_error_handlers


def create_app(overrides: dict | None = None) -> Flask:
    """Build the app. `overrides` wins over the environment, for tests."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    _register_cors(app)
    _register_blueprints(app)
    register_error_handlers(app)
    app.teardown_appcontext(close_db)

    return app


def _register_blueprints(app: Flask) -> None:
    from .routes.agent import bp as agent_bp
    from .routes.budget import bp as budget_bp
    from .routes.contributions import bp as contributions_bp
    from .routes.goals import bp as goals_bp
    from .routes.health import bp as health_bp
    from .routes.steps import bp as steps_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(steps_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(agent_bp)


def _register_cors(app: Flask) -> None:
    """A small hand-rolled CORS layer for the configured origins.

    Hand-rolled rather than flask-cors because it is twenty lines, it keeps
    the test dependencies down to Flask and pytest, and the policy is narrow
    enough to state in one place: the Vite dev server on 8060, and nothing
    else.

    In the containerised run this never fires -- nginx proxies /api on the
    frontend's own origin, so the browser makes no cross-origin request at
    all. It exists for `npm run dev` against a locally running backend.

    Preflight needs no route of its own: Flask answers OPTIONS automatically
    for every rule it knows, and this hook decorates that response on the way
    out. A catch-all OPTIONS route would be worse than useless -- it matches
    unknown paths too, turning their honest 404 into a confusing 405.
    """
    allowed = set(app.config.get("CORS_ORIGINS", ()))

    @app.after_request
    def _add_cors_headers(response):
        origin = request.headers.get("Origin")
        # Vary tells caches the response differs by Origin, so a permitted
        # origin's response is never replayed to a different one.
        response.headers.add("Vary", "Origin")
        if origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Max-Age"] = "600"
        return response
