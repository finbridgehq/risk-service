"""SQLAlchemy adapter for the outbox port of the shared kernel.

``outbox_messages`` holds every integration event this service publishes:
written with the change it announces, marked sent once the broker
acknowledged it. A failed send is retried with a growing wait (1 s, 2 s, 4 s…
up to 5 min), and the rows stay as a record of what was announced.
"""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from shared.application.outbox import Outbox, OutboxMessage
from shared.infrastructure.models import Base

MAX_RETRY_DELAY = timedelta(minutes=5)
ERROR_MAX_LENGTH = 500


class OutboxMessageModel(Base):
    """The ``outbox_messages`` table: integration events, sent or waiting."""

    __tablename__ = "outbox_messages"
    __table_args__ = (Index("ix_outbox_messages_due", "sent_at", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(80))
    topic: Mapped[str] = mapped_column(String(255))
    message_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SqlAlchemyOutbox(Outbox):
    """Stores outgoing messages in the ``outbox_messages`` table, and reads them back for the relay."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the outbox on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def add(self, message: OutboxMessage) -> None:
        self._session.add(
            OutboxMessageModel(
                event_id=message.event_id,
                event_type=message.event_type,
                topic=message.topic,
                message_key=message.key,
                payload=message.payload,
                attempts=0,
            )
        )
        await self._session.flush()

    async def find_due(self, now: datetime, limit: int) -> list[OutboxMessageModel]:
        """Return the unsent messages whose next attempt is due, oldest first.

        Args:
            now (datetime): The current time.
            limit (int): How many to return at most.
        """
        models = await self._session.scalars(
            select(OutboxMessageModel)
            .where(OutboxMessageModel.sent_at.is_(None), OutboxMessageModel.next_attempt_at <= now)
            .order_by(OutboxMessageModel.id)
            .limit(limit)
        )
        return list(models)

    @staticmethod
    def mark_sent(model: OutboxMessageModel, now: datetime) -> None:
        """Record that the broker acknowledged the message; the caller commits."""
        model.attempts += 1
        model.sent_at = now
        model.last_error = None

    @staticmethod
    def mark_failed(model: OutboxMessageModel, error: str, now: datetime) -> None:
        """Record a failed send and schedule the next one; the caller commits."""
        model.attempts += 1
        delay = min(timedelta(seconds=2 ** min(model.attempts - 1, 16)), MAX_RETRY_DELAY)
        model.next_attempt_at = now + delay
        model.last_error = (error.strip() or "No detail given")[:ERROR_MAX_LENGTH]
