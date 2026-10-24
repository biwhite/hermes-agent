"""request_restart attribution: every restart names an actor and a reason, and logs them (t_fbfe55d9)."""

import logging
from unittest.mock import AsyncMock

import pytest

from tests.gateway.restart_test_helpers import make_restart_runner

LOGGER = "gateway.run"  # run_shutdown.py logs under the gateway.run logger


def _prepared_runner():
    runner, _adapter = make_restart_runner()
    runner.stop = AsyncMock()
    runner._launch_detached_restart_command = AsyncMock()
    return runner


def _audit_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("restart_requested ")]


def test_request_restart_requires_actor_and_reason_as_keywords():
    runner = _prepared_runner()
    with pytest.raises(TypeError):
        runner.request_restart(detached=False, via_service=True)  # no actor, no reason
    with pytest.raises(TypeError):
        runner.request_restart(actor="x", detached=False, via_service=True)  # no reason
    assert runner._restart_task_started is False


@pytest.mark.parametrize("field", ["actor", "reason"])
@pytest.mark.parametrize("bad", ["", "   ", None])
def test_blank_or_none_attribution_is_refused(field, bad):
    runner = _prepared_runner()
    kwargs = {"actor": "chat:telegram:u1", "reason": "/restart chat command"}
    kwargs[field] = bad
    with pytest.raises(ValueError, match=f"non-empty {field}"):
        runner.request_restart(**kwargs)
    assert runner._restart_task_started is False


@pytest.mark.asyncio
async def test_restart_requested_logs_actor_reason_and_review_ref(caplog):
    runner = _prepared_runner()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert runner.request_restart(
            actor="control-socket:pause-for-update", reason="updater pause",
            review_ref="R-42", detached=False, via_service=True) is True
    audit = _audit_lines(caplog)
    assert len(audit) == 1
    assert "actor=control-socket:pause-for-update" in audit[0]
    assert "reason=updater pause" in audit[0]
    assert "review_ref=R-42" in audit[0]
    assert "via_service=True" in audit[0]


@pytest.mark.asyncio
async def test_missing_review_ref_is_logged_as_none(caplog):
    runner = _prepared_runner()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        runner.request_restart(actor="signal:SIGUSR1", reason="reload")
    audit = _audit_lines(caplog)
    assert len(audit) == 1
    assert "review_ref=none" in audit[0]


@pytest.mark.asyncio
async def test_newlines_in_attribution_cannot_split_the_log_line(caplog):
    runner = _prepared_runner()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        runner.request_restart(actor="chat:telegram:u1\nrestart_requested fake",
                               reason="/restart\r\nforged line")
    audit = _audit_lines(caplog)
    assert len(audit) == 1 and "fake" in audit[0]
    assert "\n" not in audit[0] and "\r" not in audit[0]


@pytest.mark.asyncio
async def test_second_request_is_refused_and_logged_with_its_own_attribution(caplog):
    runner = _prepared_runner()
    assert runner.request_restart(actor="signal:SIGUSR1", reason="first") is True
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert runner.request_restart(actor="chat:telegram:u2", reason="second") is False
    ignored = [r.getMessage() for r in caplog.records if "ignored" in r.getMessage()]
    assert ignored and "actor=chat:telegram:u2" in ignored[0] and "reason=second" in ignored[0]
    # the original attribution is the one the restart keeps
    assert runner._restart_actor == "signal:SIGUSR1"
    assert runner._restart_reason == "first"
