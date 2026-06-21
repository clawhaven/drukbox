import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

CheckStatus = Literal["ok", "fail"]

DEFAULT_CHECK_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str | None
    latency_ms: int | None
    hint: str | None = None


async def run_check(
    name: str,
    func: Callable[[], Awaitable[str | None]],
    *,
    hint: str | None = None,
    timeout: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> Check:
    """Time-box an async probe and convert outcome into a :class:`Check`.

    ``func`` returns a short detail string (or ``None``) on success. Any raised
    exception, plus timeouts, become ``status="fail"`` carrying ``hint`` — the
    owner-supplied remediation slug. The probe owner (provider / network /
    route) supplies its own hint; this helper is purely mechanical and knows
    nothing about who it is checking.
    """
    start = time.monotonic()
    try:
        detail = await asyncio.wait_for(func(), timeout=timeout)
    except TimeoutError:
        # asyncio.wait_for's TimeoutError stringifies to "", which would surface
        # as a failed check with an empty detail. Name the timeout instead.
        latency_ms = int((time.monotonic() - start) * 1000)
        return Check(
            name=name,
            status="fail",
            detail=f"timed out after {timeout:g}s",
            latency_ms=latency_ms,
            hint=hint,
        )
    except Exception as exc:
        # Broad catch on purpose: this probe is one of many running in parallel;
        # an unhandled error here must not bring peer checks down.
        latency_ms = int((time.monotonic() - start) * 1000)
        return Check(
            name=name,
            status="fail",
            detail=str(exc),
            latency_ms=latency_ms,
            hint=hint,
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    return Check(name=name, status="ok", detail=detail, latency_ms=latency_ms)
