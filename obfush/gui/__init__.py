"""Public entry points for the local obfush web interface."""

from __future__ import annotations

import threading
import webbrowser

from obfush.gui.app import create_app


def launch(
    host: str = "127.0.0.1",
    port: int = 5000,
    *,
    debug: bool = False,
    open_browser: bool = True,
) -> None:
    """Run the synchronous local GUI server."""
    app = create_app()
    if open_browser:
        url = f"http://{host}:{port}/"
        threading.Timer(0.75, webbrowser.open, args=(url,)).start()
    app.run(host=host, port=port, debug=debug, use_reloader=False)


__all__ = ["create_app", "launch"]
