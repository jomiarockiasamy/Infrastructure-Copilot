"""Local on-call desk. Bind to loopback and serve one page plus a JSON API."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config import ROOT
from src.shiftlog import add_page, get_page, list_pages, update_page
from src.triage import build_card

DESK_HTML = Path(__file__).with_name("desk.html")
DEFAULT_SHIFT = ROOT / ".desk" / "shift.sqlite"
MAX_BODY = 100_000


def handler_factory(
    shift_path: Path,
    build: Callable[[str], Any],
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler closed over the shift log and card builder."""

    class DeskHandler(BaseHTTPRequestHandler):
        """Serve the desk and the shift API."""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 0 or length > MAX_BODY:
                self._send(413, {"error": "Page is too large."})
                return None
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "Expected JSON."})
                return None
            if not isinstance(data, dict):
                self._send(400, {"error": "Expected a JSON object."})
                return None
            return data

        def _page_id(self, path: str) -> int | None:
            suffix = path.removeprefix("/api/shift/")
            if not suffix.isdigit():
                self._send(404, {"error": "Unknown page."})
                return None
            return int(suffix)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                body = DESK_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/api/shift":
                self._send(200, {"pages": list_pages(shift_path)})
                return
            if path.startswith("/api/shift/"):
                page_id = self._page_id(path)
                if page_id is None:
                    return
                page = get_page(shift_path, page_id)
                if page is None:
                    self._send(404, {"error": "Unknown page."})
                    return
                self._send(200, page)
                return
            self._send(404, {"error": "Not found."})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            data = self._read_json()
            if data is None:
                return
            if path == "/api/triage":
                text = data.get("text")
                if not isinstance(text, str) or not text.strip():
                    self._send(400, {"error": "Paste a page first."})
                    return
                card = build(text.strip())
                payload = card.to_dict() if hasattr(card, "to_dict") else card
                self._send(200, add_page(shift_path, payload))
                return
            if path.startswith("/api/shift/"):
                page_id = self._page_id(path)
                if page_id is None:
                    return
                status = data.get("status")
                checks = data.get("checks")
                if status is not None and not isinstance(status, str):
                    self._send(400, {"error": "Status must be a string."})
                    return
                if checks is not None and (
                    not isinstance(checks, list) or any(not isinstance(item, bool) for item in checks)
                ):
                    self._send(400, {"error": "Checks must be a list of booleans."})
                    return
                try:
                    page = update_page(
                        shift_path,
                        page_id,
                        status=status,
                        checks=checks,
                    )
                except ValueError as exc:
                    self._send(400, {"error": str(exc)})
                    return
                if page is None:
                    self._send(404, {"error": "Unknown page."})
                    return
                self._send(200, page)
                return
            self._send(404, {"error": "Not found."})

    return DeskHandler


def serve(
    shift_path: Path | None = None,
    build: Callable[[str], Any] | None = None,
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Listen on loopback. The caller decides when to serve forever."""
    path = shift_path or DEFAULT_SHIFT
    builder = build or build_card
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_factory(path, builder))
    return server


def main(argv: list[str] | None = None) -> int:
    """Start the on-call desk."""
    parser = argparse.ArgumentParser(description="Open the local on-call desk.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = serve(port=args.port)
    host, port = server.server_address[:2]
    print(f"On-call desk at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
