"""Domain events of the Sustainability bounded context."""
from dataclasses import dataclass

from shared.domain.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class GreenCertificationDecided(DomainEvent):
    """A certificate was checked and the decision is waiting in the outbox for Profile.

    Attributes:
        certification_id (str): The evaluation's public identifier.
        company_id (str): The MYPE's profile.
        decision (str): ``GREEN`` or ``NOT_GREEN``.
    """

    certification_id: str
    company_id: str
    decision: str
