"""Kafka consumer of Profile's verification requests.

An inbound adapter, like the green certificates' consumer, in a consumer group
of its own on the same topic: it reads a message, turns it into one call on
the application service, and confirms the message only after that call committed.

What happens to each message:

* ``CompanyVerificationRequested``: the MYPE is verified.
* Another of Profile's events: confirmed and skipped.
* Invalid (unreadable, unknown version, unacceptable facts): kept in
  ``dead_letters`` and confirmed.
* Any other failure (the storage or the database not answering, the padrón
  not loaded yet): retried in place, waiting longer each time up to a minute.
  The partition waits meanwhile, which is better than deciding without SUNAT.
"""
import asyncio
import logging
from collections.abc import Callable

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.application.messaging import DeadLetter
from shared.domain.exceptions import DomainError
from shared.infrastructure.messaging import SqlAlchemyDeadLetterStore
from shared.infrastructure.settings import KafkaSettings
from verification.application.services import CompanyVerificationApplicationService
from verification.interfaces.messages import (
    PROFILE_EVENTS_TOPIC,
    IgnoredMessage,
    InvalidMessage,
    VerificationRequestedMessage,
    parse_profile_message,
)

logger = logging.getLogger(__name__)

CLIENT_ID = "risk-service-verification"
# Profile creates its topic with its first event, maybe after this consumer started:
# ask the broker for new topics every 30 s instead of every 5 min (aiokafka's default).
METADATA_MAX_AGE_MS = 30_000
FIRST_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 60.0

type ServiceFactory = Callable[[AsyncSession], CompanyVerificationApplicationService]


class VerificationRequestsConsumer:
    """Verifies every MYPE that sends its profile to Profile for review."""

    def __init__(
        self,
        settings: KafkaSettings,
        group_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        service_factory: ServiceFactory,
        auto_offset_reset: str = "earliest",
    ) -> None:
        """Initialize the consumer; nothing connects until :meth:`run`.

        Args:
            settings (KafkaSettings): Broker address.
            group_id (str): Its own consumer group, apart from the certificates'.
            auto_offset_reset (str): Where the group starts the first time; see
                ``KycSettings.profile_offset_reset``.
            session_factory (async_sessionmaker[AsyncSession]): One session per message.
            service_factory (ServiceFactory): Builds the application service on a session.
        """
        self._settings = settings
        self._group_id = group_id
        self._auto_offset_reset = auto_offset_reset
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
            PROFILE_EVENTS_TOPIC,
            bootstrap_servers=self._settings.bootstrap_servers,
            group_id=self._group_id,
            client_id=CLIENT_ID,
            enable_auto_commit=False,
            auto_offset_reset=self._auto_offset_reset,
            metadata_max_age_ms=METADATA_MAX_AGE_MS,
        )
        await consumer.start()
        self._ready = True
        logger.info("Consuming %s as group %s", PROFILE_EVENTS_TOPIC, self._group_id)
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
            key (bytes | None): The message key (the company id).
            value (bytes | None): The message body.
        """
        parsed = parse_profile_message(value)
        if isinstance(parsed, InvalidMessage):
            await self._dead_letter(topic, partition, offset, key, value, parsed.reason, parsed.error)
            return
        if isinstance(parsed, IgnoredMessage):
            logger.debug("Skipping %s at %s[%d]@%d", parsed.event_type, topic, partition, offset)
            return
        try:
            await self._verify(parsed)
        except DomainError as error:
            await self._dead_letter(topic, partition, offset, key, value, "rejected-by-domain", str(error))

    async def _verify(self, message: VerificationRequestedMessage) -> None:
        event = message.event
        async with self._session_factory() as session:
            await self._service_factory(session).verify_company(
                event_id=event.event_id,
                request_id=event.request_id,
                company_id=event.company_id,
                user_id=event.user_id,
                ruc=event.ruc_number,
                business_name=event.business_name,
                object_key=event.ruc_document_key,
                requested_at=event.occurred_at,
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
