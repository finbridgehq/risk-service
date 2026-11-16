"""Ports for consuming integration events from a message broker.

Kafka delivers every message at least once, so a consumer must remember which
events it already applied (the inbox) and must keep, rather than drop, the
messages it cannot read (the dead letters). Both are technical concerns with no
business meaning, which is why they live in the shared kernel; each context
uses them from its own application service or consumer.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class Inbox(ABC):
    """The integration events this service already applied.

    An event is recorded in the same transaction as the change it caused, so
    a redelivered event is recognized and skipped instead of applied twice.
    """

    @abstractmethod
    async def has_processed(self, event_id: str) -> bool:
        """Return whether the event was already applied.

        Args:
            event_id (str): The event's unique identifier.
        """

    @abstractmethod
    async def record(self, event_id: str, event_type: str, aggregate_id: str) -> None:
        """Remember that the event was applied; committed with the change it caused.

        Args:
            event_id (str): The event's unique identifier.
            event_type (str): The event's name, e.g. ``AuctionCreated``.
            aggregate_id (str): The aggregate the event was about.
        """


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadLetter:
    """A message that could not be applied and is kept for a person to inspect.

    Attributes:
        topic (str): Where the message came from.
        partition (int): The topic partition.
        offset (int): The message's position in the partition.
        key (str | None): The message key, decoded as UTF-8.
        payload (str): The message body, decoded as UTF-8 (undecodable bytes replaced).
        reason (str): A short, stable code, e.g. ``unknown-event-type``.
        error (str): What went wrong, in words.
    """

    topic: str
    partition: int
    offset: int
    key: str | None
    payload: str
    reason: str
    error: str


class DeadLetterStore(ABC):
    """Where messages that cannot be applied are kept."""

    @abstractmethod
    async def add(self, dead_letter: DeadLetter) -> None:
        """Store a dead letter; the caller commits.

        Args:
            dead_letter (DeadLetter): The message and why it was rejected.
        """
