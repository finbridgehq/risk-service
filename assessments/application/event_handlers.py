"""Reactions of the Assessments context to its own domain events.

A new assessment wakes the delivery worker, so the grade reaches Investment
right away instead of at the worker's next poll. The worker lives in the
interfaces layer, so this module receives the wake-up as a plain callable.
"""
from collections.abc import Callable

from assessments.domain.events import RiskAssessmentIssued
from shared.application.events import EventBus
from shared.domain.events import DomainEvent


def register_event_handlers(event_bus: EventBus, wake_delivery: Callable[[], None]) -> None:
    """Subscribe this context's handlers; called once from the lifespan.

    Args:
        event_bus (EventBus): The process-wide event bus.
        wake_delivery (Callable[[], None]): Tells the delivery worker there is work.
    """

    async def deliver_issued_assessment(event: DomainEvent) -> None:
        wake_delivery()

    event_bus.subscribe(RiskAssessmentIssued, deliver_issued_assessment)
