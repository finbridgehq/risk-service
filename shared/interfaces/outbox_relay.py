"""Background worker that sends the outbox's messages to Kafka.

Woken as soon as a message is queued, and polling anyway every few seconds,
which covers retries and a restart halfway through a send. Messages are sent
one by one, in the order they were written, and each is marked sent only once
the broker acknowledged it: delivery is at least once, and consumers
deduplicate on the ``eventId``.

It runs in one process only (``--workers 1``), like the other workers.
"""
import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.infrastructure.outbox import SqlAlchemyOutbox
from shared.infrastructure.settings import KafkaSettings

logger = logging.getLogger(__name__)

CLIENT_ID = "risk-service-outbox"

type Clock = Callable[[], datetime]


class KafkaOutboxRelay:
    """Sends every due message of the outbox to its topic."""

    def __init__(
        self,
        settings: KafkaSettings,
        session_factory: async_sessionmaker[AsyncSession],
        poll_interval: float = 5.0,
        batch_size: int = 50,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize the relay; nothing connects until :meth:`run`.

        Args:
            settings (KafkaSettings): The broker's address.
            session_factory (async_sessionmaker[AsyncSession]): One session per pass.
            poll_interval (float): Seconds between passes when nobody wakes the relay.
            batch_size (int): Messages read per pass.
            clock (Clock): The current time, replaceable in tests.
        """
        self._settings = settings
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._clock = clock
        self._wake = asyncio.Event()
        self._producer: AIOKafkaProducer | None = None

    def wake(self) -> None:
        """Ask for a pass now instead of at the next poll."""
        self._wake.set()

    async def run(self) -> None:
        """Connect and send due messages until cancelled; the connection is closed on the way out."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.bootstrap_servers, client_id=CLIENT_ID, acks="all"
        )
        await self._producer.start()
        try:
            while True:
                self._wake.clear()
                if await self.relay_due() == self._batch_size:
                    continue  # A full batch: there may be more due right now.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
        finally:
            await self._producer.stop()
            self._producer = None

    async def relay_due(self) -> int:
        """Make one pass: send every message that is due, in order.

        Stops at the first failure: the broker is most likely down, and the
        failed message waits for its next attempt. A later message may then go
        first; consumers must not depend on the order across retries (Profile
        ignores a decision about an upload that is no longer the latest).

        Returns:
            int: How many messages were sent in this pass.
        """
        if self._producer is None:
            raise RuntimeError("The relay is not running")
        async with self._session_factory() as session:
            outbox = SqlAlchemyOutbox(session)
            due = await outbox.find_due(self._clock(), self._batch_size)
            sent = 0
            for model in due:
                try:
                    await self._producer.send_and_wait(
                        model.topic,
                        value=json.dumps(model.payload, ensure_ascii=False).encode(),
                        key=model.message_key.encode(),
                    )
                except KafkaError as error:
                    outbox.mark_failed(model, f"{type(error).__name__}: {error}", self._clock())
                    logger.warning("Could not send %s %s; retrying later: %s", model.event_type, model.event_id, error)
                    break
                outbox.mark_sent(model, self._clock())
                sent += 1
                logger.info("Sent %s %s to %s", model.event_type, model.event_id, model.topic)
            await session.commit()
        return sent
