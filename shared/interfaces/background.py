"""Long-running background tasks started and stopped with the application.

A Kafka consumer or a polling worker runs for the whole life of the process,
next to the HTTP server. A bare ``asyncio.create_task`` would lose an
exception silently and leave the process serving HTTP with the work stopped;
:class:`BackgroundTask` logs every failure, starts the work again after a
pause that doubles each time (up to 30 s), and stops it cleanly on shutdown.
"""
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

FIRST_RESTART_DELAY = 1.0
MAX_RESTART_DELAY = 30.0


class BackgroundTask:
    """Runs a coroutine function for the life of the application, restarting it when it fails."""

    def __init__(self, name: str, target: Callable[[], Awaitable[None]]) -> None:
        """Initialize the task; nothing runs until :meth:`start`.

        Args:
            name (str): Shown in the logs, e.g. ``auction-lifecycle-consumer``.
            target (Callable[[], Awaitable[None]]): The work, meant to run until cancelled.
        """
        self._name = name
        self._target = target
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the task was started and has not stopped."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the work in the running event loop."""
        self._task = asyncio.create_task(self._supervise(), name=self._name)

    async def stop(self) -> None:
        """Cancel the work and wait until it has finished cleaning up."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _supervise(self) -> None:
        delay = FIRST_RESTART_DELAY
        while True:
            try:
                await self._target()
                logger.warning("%s returned; starting it again in %.0fs", self._name, delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s failed; starting it again in %.0fs", self._name, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RESTART_DELAY)
