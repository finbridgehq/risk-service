"""Reactions of the Sustainability context to its own domain events.

A decision wakes the outbox relay, so it reaches Profile right away instead of
at the relay's next poll. The relay lives in the interfaces layer, so this
module receives the wake-up as a plain callable.
"""
from collections.abc import Callable

from shared.application.events import EventBus
from shared.domain.events import DomainEvent
from sustainability.domain.events import GreenCertificationDecided


def register_event_handlers(event_bus: EventBus, wake_relay: Callable[[], None]) -> None:
    """Subscribe this context's handlers; called once from the lifespan.

    Args:
        event_bus (EventBus): The process-wide event bus.
        wake_relay (Callable[[], None]): Tells the outbox relay there is work.
    """

    async def send_decision(event: DomainEvent) -> None:
        wake_relay()

    event_bus.subscribe(GreenCertificationDecided, send_decision)
