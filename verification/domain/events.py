"""Domain events of the Verification bounded context."""
from dataclasses import dataclass

from shared.domain.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyVerificationDecided(DomainEvent):
    """A MYPE was checked and the decision is waiting in the outbox for Profile.

    Attributes:
        verification_id (str): The verification's public identifier.
        company_id (str): The MYPE's profile.
        decision (str): ``VERIFIED``, ``REJECTED`` or ``CORRECTION_REQUIRED``.
    """

    verification_id: str
    company_id: str
    decision: str
