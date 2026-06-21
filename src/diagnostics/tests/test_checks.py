import asyncio
import dataclasses

import pytest

from diagnostics.checks import Check, run_check


async def test_run_check_returns_ok_with_detail_and_latency() -> None:
    """A successful probe records its detail and a measured latency."""

    async def _probe() -> str:
        return "all good"

    check = await run_check("provider", _probe, hint="check_aws_credentials_and_region")
    assert check.status == "ok"
    assert check.detail == "all good"
    assert check.latency_ms is not None
    assert check.latency_ms >= 0
    # Hint is only attached on failure; a passing probe carries none.
    assert check.hint is None


async def test_run_check_attaches_owner_hint_on_failure() -> None:
    """A raised exception becomes a fail carrying the owner-supplied hint."""

    async def _probe() -> str:
        raise RuntimeError("403 Forbidden")

    check = await run_check("provider", _probe, hint="check_aws_credentials_and_region")
    assert check.status == "fail"
    assert check.detail == "403 Forbidden"
    assert check.hint == "check_aws_credentials_and_region"


async def test_run_check_attaches_hint_on_timeout() -> None:
    """A hung probe is killed by the deadline and still carries the hint."""

    async def _probe() -> str:
        await asyncio.sleep(10.0)
        return "never"

    check = await run_check(
        "provider", _probe, hint="check_aws_credentials_and_region", timeout=0.05
    )
    assert check.status == "fail"
    assert check.hint == "check_aws_credentials_and_region"
    # A bare TimeoutError stringifies to "" — the detail must name the timeout.
    assert check.detail == "timed out after 0.05s"


def test_check_is_frozen() -> None:
    """Check is immutable — pipelines never want surprise mutation."""
    check = Check(name="x", status="ok", detail=None, latency_ms=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.detail = "mutated"  # type: ignore[misc]
