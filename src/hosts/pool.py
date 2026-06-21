import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select

from core.database import async_session_factory
from core.settings import Settings, get_settings
from hosts.models import Host, HostStatus
from hosts.service import HostService, utc_now
from networking.tailscale import Tailscale

log = logging.getLogger(__name__)

# Bail out after this many consecutive create failures (broker outage scenario)
# rather than logging the same failure pool_size times per tick.
_MAX_CONSECUTIVE_CREATE_FAILURES = 3


@dataclass(frozen=True)
class PoolMaintenanceSummary:
    created: int = 0
    removed_excess: int = 0
    pool_size: int = 0


async def maintain_pool() -> PoolMaintenanceSummary:
    """Top up / shrink the warm-host pool and reap failed pool members.

    Each tick creates at most ``POOL_MAX_CREATES_PER_TICK`` hosts. Overlapping
    ticks or accidental scheduler replicas can therefore over-provision by at
    most that batch size, which the next tick sheds via the excess path. This
    intentionally avoids any cross-tick locking — see CONTRIBUTING for context.
    """
    settings = get_settings()
    if settings.pool_size <= 0:
        return PoolMaintenanceSummary(pool_size=settings.pool_size)
    tailscale: Tailscale | None = Tailscale.from_settings() if settings.tailscale_enabled else None
    try:
        return await _maintain(settings, tailscale)
    finally:
        if tailscale is not None:
            await tailscale.aclose()


async def _maintain(settings: Settings, tailscale: Tailscale | None) -> PoolMaintenanceSummary:
    now = utc_now()

    async with async_session_factory() as session:
        # Count warm pool members that are still fresh and unclaimed. Only
        # pool_member hosts count — demand-provisioned hosts also keep
        # claimed_at NULL but must never be counted or shed. Exclude hosts whose
        # expires_at has already passed — those are queued for janitor reaping.
        current = await session.scalar(
            select(func.count())
            .select_from(Host)
            .where(Host.pool_member.is_(True))
            .where(Host.claimed_at.is_(None))
            .where(Host.status != HostStatus.ERROR.value)
            .where(or_(Host.expires_at.is_(None), Host.expires_at > now))
        )
        current = current or 0

        excess_ids: list = []
        if current > settings.pool_size:
            shed = current - settings.pool_size
            excess_ids = list(
                (
                    await session.execute(
                        select(Host.id)
                        .where(Host.pool_member.is_(True))
                        .where(Host.claimed_at.is_(None))
                        .where(Host.status != HostStatus.ERROR.value)
                        .where(or_(Host.expires_at.is_(None), Host.expires_at > now))
                        .order_by(Host.created_at.asc())
                        .limit(shed)
                    )
                ).scalars()
            )

    deficit = max(settings.pool_size - current, 0)
    batch = min(deficit, settings.pool_max_creates_per_tick)

    created = 0
    consecutive_failures = 0
    for _ in range(batch):
        try:
            async with async_session_factory() as session:
                service = HostService(session, settings=settings, tailscale=tailscale)
                expires_at = utc_now() + timedelta(hours=settings.pool_host_max_age_hours)
                await service.create_host(
                    env={},
                    image=None,
                    expires_at=expires_at,
                    pool_member=True,
                )
                created += 1
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            log.exception("pool: failed to create pool host")
            if consecutive_failures >= _MAX_CONSECUTIVE_CREATE_FAILURES:
                log.error(
                    "pool: aborting top-up after %d consecutive failures",
                    consecutive_failures,
                )
                break

    removed_excess = 0
    for host_id in excess_ids:
        try:
            async with async_session_factory() as session:
                service = HostService(session, settings=settings, tailscale=tailscale)
                await service.delete_host(host_id, pool_shed=True)
                removed_excess += 1
        except Exception:
            log.exception("pool: failed to shed excess pool host_id=%s", host_id)

    if created or removed_excess:
        log.info(
            "pool: maintained (created=%d, removed_excess=%d, target=%d)",
            created,
            removed_excess,
            settings.pool_size,
        )

    return PoolMaintenanceSummary(
        created=created,
        removed_excess=removed_excess,
        pool_size=settings.pool_size,
    )


if __name__ == "__main__":
    # Cron entry point: `python -m hosts.pool`.
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(maintain_pool())
