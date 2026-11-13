"""Servidor HTTP local para el informe HTML en tiempo real."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from typing import Any
from urllib.parse import urlparse

from app.core.reports import ReportService

logger = logging.getLogger(__name__)


def create_live_server(
    service: ReportService,
    session_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_s: int = 5,
) -> ThreadingHTTPServer:
    """Crea (sin iniciar) un servidor que regenera el informe en cada petición.

    Sin ``session_id`` siempre se sirve la sesión más reciente, de modo que el
    informe sigue al monitor aunque se reinicie.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (API de http.server)
            if urlparse(self.path).path != "/":
                self._send(404, "No encontrado", "text/plain; charset=utf-8")
                return
            try:
                html = service.generate_html(session_id, live_refresh_s=refresh_s)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Error generando informe en vivo: %s", exc)
                self._send(500, f"Error: {exc}", "text/plain; charset=utf-8")
                return
            self._send(200, html, "text/html; charset=utf-8")

        def _send(self, status: int, body: str, content_type: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug("live-report: " + format, *args)

    return ThreadingHTTPServer((host, port), Handler)
