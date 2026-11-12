"""Repository port of the Verification bounded context."""
from abc import ABC, abstractmethod

from verification.domain.entities import CompanyVerification


class CompanyVerificationRepository(ABC):
    """Collection-like access to :class:`CompanyVerification` aggregates."""

    @abstractmethod
    async def save(self, company_verification: CompanyVerification) -> CompanyVerification:
        """Insert a decision.

        Returns:
            CompanyVerification: The aggregate as stored, with its ``id`` assigned.
        """

    @abstractmethod
    async def find_by_request_id(self, request_id: str) -> CompanyVerification | None:
        """Return the decision on one request, or ``None`` if it was not decided yet."""
