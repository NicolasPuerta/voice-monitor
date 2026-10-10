"""Pruebas del SystemContextBuilder y la agrupacin de procesos."""

from datetime import datetime, timezone
from pydantic import AwareDatetime

from app.collectors.health import SourceHealthManager, SourceState
from app.core.context import SystemContextBuilder
from app.domain.snapshots import (
    ProcessSnapshot,
    ResourceSnapshot,
)

NOW: AwareDatetime = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_dummy_resources() -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu_percent=10.0,
        cpu_count_logical=4,
        memory_total_bytes=1000,
        memory_used_bytes=500,
        memory_available_bytes=500,
        memory_percent=50.0,
    )


def test_context_builder_firefox_with_children() -> None:
    health = SourceHealthManager()
    builder = SystemContextBuilder()

    processes = [
        ProcessSnapshot(
            pid=100,
            name="bash",
            parent_pid=1,
            cgroup="/user.slice/session-1.scope",
            executable="/bin/bash",
        ),
        ProcessSnapshot(
            pid=200,
            name="firefox",
            parent_pid=100,
            cgroup="/user.slice/app-gnome-firefox-123.scope",
            executable="/usr/bin/firefox",
            cpu_percent=10.0,
            memory_rss_bytes=100,
        ),
        ProcessSnapshot(
            pid=201,
            name="Web Content",
            parent_pid=200,
            cgroup="/user.slice/app-gnome-firefox-123.scope",
            executable="/usr/bin/firefox",
            cpu_percent=20.0,
            memory_rss_bytes=200,
        ),
    ]

    ctx = builder.build(
        collected_at=NOW,
        resources=make_dummy_resources(),
        processes=processes,
        health_manager=health,
    )

    assert len(ctx.apps) == 2

    # Firefox group
    firefox_app = next(a for a in ctx.apps if a.name == "firefox")
    assert firefox_app.app_key == "cgroup:/user.slice/app-gnome-firefox-123.scope"
    assert firefox_app.cpu_percent == 30.0
    assert firefox_app.memory_rss_bytes == 300
    assert len(firefox_app.processes) == 2

    # Bash group
    bash_app = next(a for a in ctx.apps if a.name == "bash")
    assert bash_app.app_key == "exe:/bin/bash"
    assert len(bash_app.processes) == 1


def test_context_builder_python_unknown() -> None:
    health = SourceHealthManager()
    builder = SystemContextBuilder()

    processes = [
        ProcessSnapshot(
            pid=300,
            name="python3",
            parent_pid=1,
            cmdline="python3 /opt/scripts/unknown_worker.py",
            executable="/usr/bin/python3",
        ),
        ProcessSnapshot(
            pid=301, name="sh", parent_pid=300, cmdline="sh -c echo", executable="/bin/sh"
        ),
    ]

    ctx = builder.build(
        collected_at=NOW,
        resources=make_dummy_resources(),
        processes=processes,
        health_manager=health,
    )

    # Should group them together under the python script
    assert len(ctx.apps) == 1
    app = ctx.apps[0]
    assert app.name == "python3 (unknown_worker.py)"
    assert app.app_key == "cmd:python3 /opt/scripts/unknown_worker.py"
    assert len(app.processes) == 2


def test_context_builder_absent_cgroup_and_health() -> None:
    health = SourceHealthManager()
    health.set_state("psi", SourceState.DISABLED, "no psi")
    health.set_state("energy", SourceState.DEGRADED, "no perms")

    builder = SystemContextBuilder()

    processes = [
        ProcessSnapshot(
            pid=400,
            name="my_binary",
            parent_pid=1,
            executable="/usr/local/bin/my_binary",
            cgroup=None,  # Cgroup absent
        )
    ]

    ctx = builder.build(
        collected_at=NOW,
        resources=make_dummy_resources(),
        processes=processes,
        health_manager=health,
    )

    assert len(ctx.apps) == 1
    assert ctx.apps[0].app_key == "exe:/usr/local/bin/my_binary"

    # Verify health states are propagated
    assert ctx.source_health["psi"] == "disabled"
    assert ctx.source_health["energy"] == "degraded"
    assert ctx.source_health["system_resources"] == "ok"


def test_context_builder_handles_broken_process_tree() -> None:
    health = SourceHealthManager()
    builder = SystemContextBuilder()

    processes = [
        ProcessSnapshot(
            pid=500,
            name="orphan_proc",
            parent_pid=9999,  # Parent not in list
            executable="/bin/orphan",
            cgroup=None,
        )
    ]

    ctx = builder.build(
        collected_at=NOW,
        resources=make_dummy_resources(),
        processes=processes,
        health_manager=health,
    )

    assert len(ctx.apps) == 1
    assert ctx.apps[0].app_key == "exe:/bin/orphan"
    assert ctx.apps[0].processes[0].pid == 500
