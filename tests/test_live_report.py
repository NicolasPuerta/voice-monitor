"""Pruebas del informe HTML en tiempo real."""

from datetime import datetime, timezone
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from app.cli import build_parser
from app.core.live_report import create_live_server
from app.core.reports import ReportService, inject_live_script
from app.storage.db import BackgroundDatabase


@pytest.fixture
def service(tmp_path: Path) -> ReportService:
    db_file = tmp_path / "live.db"
    db = BackgroundDatabase(db_file)
    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (
            "session_live_1",
            datetime(2026, 10, 13, 11, 0, 0, tzinfo=timezone.utc).isoformat(),
            None,
        ),
    )
    db.stop()
    return ReportService(db_file)


def test_inject_live_script_before_body_end() -> None:
    html = inject_live_script("<html><body><p>x</p></body></html>", 7)
    assert "EN VIVO" in html and "var seconds = 7;" in html
    assert html.index("<script>") < html.index("</body>")


def test_generate_html_live_flag(service: ReportService) -> None:
    assert "EN VIVO" not in service.generate_html()
    assert "EN VIVO" in service.generate_html(live_refresh_s=3)


def test_live_server_serves_updated_report(service: ReportService) -> None:
    server = create_live_server(service, port=0, refresh_s=2)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        body = urlopen(url, timeout=5).read().decode("utf-8")  # noqa: S310
        assert "session_live_1" in body and "EN VIVO" in body
        with pytest.raises(HTTPError) as err:
            urlopen(url + "otra", timeout=5)  # noqa: S310
        assert err.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_report_live_arguments() -> None:
    args = build_parser().parse_args(["report", "--live", "--port", "9000"])
    assert args.live is True and args.port == 9000 and args.refresh == 5
