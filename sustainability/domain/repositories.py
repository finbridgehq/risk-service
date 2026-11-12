"""Repository port of the Sustainability bounded context."""
from abc import ABC, abstractmethod

from sustainability.domain.entities import GreenCertification


class GreenCertificationRepository(ABC):
    """Collection-like access to :class:`GreenCertification` aggregates."""

    @abstractmethod
    async def save(self, green_certification: GreenCertification) -> GreenCertification:
        """Insert a decision.

        Returns:
            GreenCertification: The aggregate as stored, with its ``id`` assigned.
        """

    @abstractmethod
    async def find_by_submission_id(self, submission_id: str) -> GreenCertification | None:
        """Return the decision on one upload, or ``None`` if it was not decided yet."""

    @abstractmethod
    async def find_latest_by_user_id(self, user_id: str) -> GreenCertification | None:
        """Return the MYPE's most recently uploaded certificate that was decided, or ``None``.

        Args:
            user_id (str): The MYPE's IAM account, the ``mypeId`` of its auctions.
        """
