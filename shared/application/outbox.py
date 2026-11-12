"""Port for publishing integration events through a transactional outbox.

An event that leaves the service is written to the outbox in the same
transaction as the change it announces, and a relay sends it to the broker
afterwards. If the broker is down, the event waits in the table instead of
being lost, and a rolled-back change never announces anything. A technical
concern with no business meaning, like the inbox, so it lives in the kernel.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxMessage:
    """An integration event waiting to be sent.

    Attributes:
        event_id (str): The event's unique identifier; consumers deduplicate on it.
        event_type (str): Its name, e.g. ``GreenCertificationIssued``.
        topic (str): Where it goes.
        key (str): The message key; events with the same key keep their order.
        payload (dict[str, Any]): The whole message, as JSON-serializable values.
    """

    event_id: str
    event_type: str
    topic: str
    key: str
    payload: dict[str, Any]


class Outbox(ABC):
    """Where integration events wait until the relay sends them."""

    @abstractmethod
    async def add(self, message: OutboxMessage) -> None:
        """Queue a message; the caller commits it with the change it announces.

        Args:
            message (OutboxMessage): The event to send.
        """
