"""Domain events of the Assessments bounded context."""
from dataclasses import dataclass

from shared.domain.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskAssessmentIssued(DomainEvent):
    """An auction was assessed and the decision is waiting to reach Investment.

    Attributes:
        auction_id (str): The auction that was graded.
        assessment_id (str): The assessment's public identifier.
        risk_grade (str | None): The grade it was given; ``None`` if it was rejected.
    """

    auction_id: str
    assessment_id: str
    risk_grade: str | None
