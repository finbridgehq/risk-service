"""SQLAlchemy adapters for the messaging ports of the shared kernel.

``processed_events`` is the inbox: one row per integration event applied,
written in the same transaction as the change it caused. ``dead_letters``
keeps the messages that could not be applied, so a person can inspect them
with SQL instead of finding them only in a log.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from shared.application.messaging import DeadLetter, DeadLetterStore, Inbox
from shared.infrastructure.models import Base


class ProcessedEventModel(Base):
    """The ``processed_events`` table: the integration events already applied."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadLetterModel(Base):
    """The ``dead_letters`` table: messages that could not be applied."""

    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(255))
    partition: Mapped[int] = mapped_column(Integer)
    offset: Mapped[int] = mapped_column(BigInteger)
    message_key: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(80))
    error: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SqlAlchemyInbox(Inbox):
    """Stores the processed events in the ``processed_events`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the inbox on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def has_processed(self, event_id: str) -> bool:
        return await self._session.get(ProcessedEventModel, event_id) is not None

    async def record(self, event_id: str, event_type: str, aggregate_id: str) -> None:
        self._session.add(ProcessedEventModel(event_id=event_id, event_type=event_type, aggregate_id=aggregate_id))
        await self._session.flush()


class SqlAlchemyDeadLetterStore(DeadLetterStore):
    """Stores dead letters in the ``dead_letters`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the store on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def add(self, dead_letter: DeadLetter) -> None:
        self._session.add(
            DeadLetterModel(
                topic=dead_letter.topic,
                partition=dead_letter.partition,
                offset=dead_letter.offset,
                message_key=dead_letter.key[:255] if dead_letter.key is not None else None,
                payload=dead_letter.payload,
                reason=dead_letter.reason[:80],
                error=dead_letter.error,
            )
        )
        await self._session.flush()
