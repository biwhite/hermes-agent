"""Control-socket pause-for-update restart attribution (t_fbfe55d9).

Drives the real ``_pause_for_update_handler`` closure built by
``_start_gateway_start_control_socket`` (captured from the verb table; no socket is bound) and asserts
the actor and reason reach ``request_restart`` and the "Restart requested" log line.
"""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

import gateway.control_socket as control_socket
from gateway import run_bootstrap
from tests.gateway.restart_test_helpers import make_restart_runner

LOGGER = "gateway.run"


class _CapturingControlServer:
    """Stands in for GatewayControlServer: records verb handlers, never binds a socket."""

    captured: dict = {}

    def __init__(self, *args, verb_handlers=None, **kwargs):
        type(self).captured = dict(verb_handlers or {})
        self.ticket_store = None

    async def start(self):
        return True

    def cleanup_files(self):
        return None


@pytest.mark.asyncio
async def test_pause_for_update_handler_passes_actor_and_reason_to_request_restart(
        monkeypatch, caplog):
    runner, _adapter = make_restart_runner()
    runner.stop = AsyncMock()
    runner._launch_detached_restart_command = AsyncMock()
    runner.session_runtime_descriptor = {"state": "ready", "served_profiles": [], "capabilities": []}
    runner.session_ticket_store = None
    monkeypatch.setattr(control_socket, "GatewayControlServer", _CapturingControlServer)

    seen = {}
    real_request_restart = runner.request_restart

    def spy(**kwargs):
        seen.update(kwargs)
        return real_request_restart(**kwargs)

    runner.request_restart = spy

    await run_bootstrap._start_gateway_start_control_socket(runner)
    handler = _CapturingControlServer.captured["pause-for-update"]

    with caplog.at_level(logging.INFO, logger=LOGGER):
        # The handler blocks on a threading.Event while the loop runs _request, so run it off-loop.
        result = await asyncio.to_thread(handler)

    assert result["pausing"] is True
    assert seen["actor"] == "control-socket:pause-for-update"
    assert "client identity not verified" in seen["reason"]
    assert seen["via_service"] is True and seen["detached"] is False

    audit = [r.getMessage() for r in caplog.records if r.getMessage().startswith("restart_requested ")]
    assert len(audit) == 1, f"expected one restart_requested audit line, got {audit}"
    assert "actor=control-socket:pause-for-update" in audit[0]
    assert "client identity not verified" in audit[0]
    assert "review_ref=none" in audit[0] and "via_service=True" in audit[0]
