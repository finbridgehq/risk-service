"""Background worker that delivers pending assessments to Investment.

An assessment is committed first and delivered after, the same outbox shape
Investment uses for its own events: if Investment is down, the grade is not
lost, it waits in ``risk_assessments`` until a later attempt succeeds. The
worker is woken as soon as an assessment is issued, and polls anyway every few
seconds, which covers retries and a restart halfway through a delivery.

It runs in one process only (``--workers 1``): two workers would deliver the
same assessment twice. That would be harmless, since Investment ignores a
repeated assessment id, but wasteful.
"""
import asyncio
import contextlib
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assessments.application.services import RiskAssessmentApplicationService

logger = logging.getLogger(__name__)

type ServiceFactory = Callable[[AsyncSession], RiskAssessmentApplicationService]


class EvaluationDeliveryWorker:
    """Delivers every pending assessment whose next attempt is due."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service_factory: ServiceFactory,
        poll_interval: float = 5.0,
        batch_size: int = 20,
    ) -> None:
        """Initialize the worker; nothing runs until :meth:`run`.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): One session per delivery.
            service_factory (ServiceFactory): Builds the application service on a session.
            poll_interval (float): Seconds between passes when nobody wakes the worker.
            batch_size (int): Assessments read per pass.
        """
        self._session_factory = session_factory
        self._service_factory = service_factory
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Ask for a pass now instead of at the next poll."""
        self._wake.set()

    async def run(self) -> None:
        """Deliver due assessments until cancelled."""
        while True:
            self._wake.clear()
            if await self.deliver_due() == self._batch_size:
                continue  # A full batch: there may be more due right now.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)

    async def deliver_due(self) -> int:
        """Make one pass: try to deliver every assessment that is due.

        Returns:
            int: How many assessments were attempted without an unexpected
            failure; a failing one keeps its schedule and waits for the next poll.
        """
        async with self._session_factory() as session:
            due = await self._service_factory(session).get_assessments_due_for_delivery(self._batch_size)
        attempted = 0
        for assessment in due:
            auction_id = assessment.facts.auction_id.value
            try:
                async with self._session_factory() as session:
                    await self._service_factory(session).deliver_assessment(auction_id)
                attempted += 1
            except Exception:
                logger.exception("Delivery of the assessment of auction %s failed unexpectedly", auction_id)
        return attempted
