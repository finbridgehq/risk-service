"""Kafka consumer of Investment's auction-lifecycle topic.

An inbound adapter, like a route: it reads a message, turns it into one call
on the application service, and confirms the message only after that call
committed. Delivery is at least once; the service's inbox makes a redelivered
event harmless.

What happens to each message:

* ``AuctionCreated``: the auction is assessed.
* Another event of the contract: confirmed and skipped.
* Invalid (unreadable, unknown type or version, unacceptable facts): kept in
  ``dead_letters`` and confirmed, so one bad message never blocks the topic.
* Any other failure (database down…): retried in place, waiting longer each
  time, and confirmed only once it succeeds. The partition waits meanwhile,
  which keeps the events of one auction in order.
"""
import asyncio
import logging
from collections.abc import Callable

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assessments.application.services import RiskAssessmentApplicationService
from assessments.interfaces.messages import (
    AUCTION_LIFECYCLE_TOPIC,
    AuctionCreatedMessage,
    IgnoredMessage,
    InvalidMessage,
    parse_auction_lifecycle_message,
)
from shared.application.messaging import DeadLetter
from shared.domain.exceptions import DomainError
from shared.infrastructure.messaging import SqlAlchemyDeadLetterStore
from shared.infrastructure.settings import KafkaSettings

logger = logging.getLogger(__name__)

CLIENT_ID = "risk-service"
FIRST_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 60.0

type ServiceFactory = Callable[[AsyncSession], RiskAssessmentApplicationService]


class AuctionLifecycleConsumer:
    """Assesses every auction Investment creates."""

    def __init__(
        self,
        settings: KafkaSettings,
        session_factory: async_sessionmaker[AsyncSession],
        service_factory: ServiceFactory,
    ) -> None:
        """Initialize the consumer; nothing connects until :meth:`run`.

        Args:
            settings (KafkaSettings): Broker address, group and offset reset.
            session_factory (async_sessionmaker[AsyncSession]): One session per message.
            service_factory (ServiceFactory): Builds the application service on a session.
        """
        self._settings = settings
        self._session_factory = session_factory
        self._service_factory = service_factory
        self._ready = False

    @property
    def ready(self) -> bool:
        """Whether the consumer is connected and reading."""
        return self._ready

    async def run(self) -> None:
        """Connect and consume until cancelled; the connection is closed on the way out."""
        consumer = AIOKafkaConsumer(
            AUCTION_LIFECYCLE_TOPIC,
            bootstrap_servers=self._settings.bootstrap_servers,
            group_id=self._settings.group_id,
            client_id=CLIENT_ID,
            enable_auto_commit=False,
            auto_offset_reset=self._settings.auto_offset_reset,
        )
        await consumer.start()
        self._ready = True
        logger.info("Consuming %s as group %s", AUCTION_LIFECYCLE_TOPIC, self._settings.group_id)
        try:
            async for record in consumer:
                await self._handle_until_done(record)
                await consumer.commit({TopicPartition(record.topic, record.partition): record.offset + 1})
        finally:
            self._ready = False
            await consumer.stop()

    async def handle(self, *, topic: str, partition: int, offset: int, key: bytes | None, value: bytes | None) -> None:
        """Apply one message; raises only for failures worth retrying.

        Args:
            topic (str): Where the message came from.
            partition (int): The topic partition.
            offset (int): The message's position in the partition.
            key (bytes | None): The message key (the auction id).
            value (bytes | None): The message body.
        """
        parsed = parse_auction_lifecycle_message(value)
        if isinstance(parsed, InvalidMessage):
            await self._dead_letter(topic, partition, offset, key, value, parsed.reason, parsed.error)
            return
        if isinstance(parsed, IgnoredMessage):
            logger.debug("Skipping %s at %s[%d]@%d", parsed.event_type, topic, partition, offset)
            return
        try:
            await self._assess(parsed)
        except DomainError as error:
            await self._dead_letter(topic, partition, offset, key, value, "rejected-by-domain", str(error))

    async def _assess(self, message: AuctionCreatedMessage) -> None:
        envelope, data = message.envelope, message.data
        async with self._session_factory() as session:
            await self._service_factory(session).assess_auction(
                event_id=str(envelope.event_id),
                auction_id=envelope.aggregate_id,
                invoice_id=data.invoice_id,
                mype_id=data.mype_id,
                payer_ruc=data.payer_ruc,
                payer_name=data.payer_name,
                due_date=data.due_date,
                invoice_amount=data.invoice_amount,
                currency=data.currency,
                green_certified=data.green_certified,
            )

    async def _handle_until_done(self, record: ConsumerRecord[bytes, bytes]) -> None:
        delay = FIRST_RETRY_DELAY
        while True:
            try:
                await self.handle(
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                    key=record.key,
                    value=record.value,
                )
                return
            except Exception:
                logger.exception(
                    "Could not apply %s[%d]@%d; retrying in %.0fs", record.topic, record.partition, record.offset, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)

    async def _dead_letter(
        self, topic: str, partition: int, offset: int, key: bytes | None, value: bytes | None, reason: str, error: str
    ) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyDeadLetterStore(session).add(
                DeadLetter(
                    topic=topic,
                    partition=partition,
                    offset=offset,
                    key=key.decode(errors="replace") if key is not None else None,
                    payload=value.decode(errors="replace") if value is not None else "",
                    reason=reason,
                    error=error,
                )
            )
            await session.commit()
        logger.error("Dead-lettered %s[%d]@%d (%s): %s", topic, partition, offset, reason, error)
