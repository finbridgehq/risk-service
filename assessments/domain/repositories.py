"""Repository port of the Assessments bounded context.

The domain says what it needs from persistence; ``infrastructure`` says how.
The methods are ``async`` because every implementation does I/O, but the
domain objects themselves never await anything.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from assessments.domain.entities import RiskAssessment
from assessments.domain.value_objects import AuctionId, NewsScreening


class RiskAssessmentRepository(ABC):
    """Collection-like access to :class:`RiskAssessment` aggregates."""

    @abstractmethod
    async def save(self, risk_assessment: RiskAssessment) -> RiskAssessment:
        """Insert or update a risk assessment.

        Returns:
            RiskAssessment: The aggregate as stored, with its ``id`` assigned.
        """

    @abstractmethod
    async def find_by_auction_id(self, auction_id: AuctionId) -> RiskAssessment | None:
        """Return the assessment of an auction, or ``None`` if it was never assessed."""

    @abstractmethod
    async def find_due_for_delivery(self, now: datetime, limit: int) -> list[RiskAssessment]:
        """Return pending assessments whose next delivery is due, oldest first.

        Args:
            now (datetime): The current time, in UTC.
            limit (int): The most assessments to return.
        """


class NewsScreeningRepository(ABC):
    """The latest news search for each payer, so the same payer is not searched again for a while."""

    @abstractmethod
    async def find_since(self, ruc: str, since: datetime) -> NewsScreening | None:
        """Return the payer's last search if it ran at ``since`` or later, else ``None``."""

    @abstractmethod
    async def save(self, screening: NewsScreening) -> None:
        """Keep a search, replacing the payer's previous one."""
