"""Flask application factory for the local GUI."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template

from obfush.gui.api import JSON_LIMIT_BYTES, api


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create an isolated Flask application suitable for serving or tests."""
    app = Flask(__name__)
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=JSON_LIMIT_BYTES,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    app.register_blueprint(api)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.errorhandler(413)
    def request_too_large(error):
        del error
        return jsonify({
            "error": {
                "code": "payload_too_large",
                "message": "JSON request body must not exceed 1 MiB",
            }
        }), 413

    return app
