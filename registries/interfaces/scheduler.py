"""Daily refresh of SUNAT's registries from the running service.

The refresh runs as a subprocess (``python -m registries refresh``) so that
streaming 1.6 GB never blocks the API's event loop, and its output goes to the
same log as the service. It runs once at start-up (cheap when nothing changed:
one HEAD per registry) and then every day at the configured hour.
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from registries.infrastructure.settings import RegistrySettings

logger = logging.getLogger(__name__)


class RegistryRefreshScheduler:
    """Launches the registry refresh at start-up and then once a day."""

    def __init__(self, settings: RegistrySettings) -> None:
        """Initialize the scheduler; nothing runs until :meth:`run`.

        Args:
            settings (RegistrySettings): The hour and time zone of the daily refresh.
        """
        self._settings = settings

    async def run(self) -> None:
        """Refresh now, then every day at the configured hour, until cancelled."""
        while True:
            await self.refresh_once()
            delay = self.seconds_until_next_run(datetime.now(ZoneInfo(self._settings.timezone)))
            logger.info("Next registry refresh in %.0f minutes", delay / 60)
            await asyncio.sleep(delay)

    async def refresh_once(self) -> int:
        """Run ``python -m registries refresh`` and wait for it.

        Returns:
            int: The subprocess's exit code.
        """
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "registries", "refresh")
        try:
            code = await process.wait()
        except asyncio.CancelledError:
            process.terminate()
            await process.wait()
            raise
        if code != 0:
            logger.error("Registry refresh exited with code %d; the previous copy is still in use", code)
        return code

    def seconds_until_next_run(self, now: datetime) -> float:
        """Seconds from ``now`` to the next ``refresh_hour`` o'clock in the configured zone."""
        next_run = now.replace(hour=self._settings.refresh_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return (next_run - now).total_seconds()
