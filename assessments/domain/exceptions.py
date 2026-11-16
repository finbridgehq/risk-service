"""Domain exceptions of the Assessments bounded context."""
from shared.domain.exceptions import NotFoundError


class RiskAssessmentNotFoundError(NotFoundError):
    """No risk assessment exists for the given auction."""

    def __init__(self, auction_id: str) -> None:
        """Build the message from the auction that was looked up.

        Args:
            auction_id (str): The auction whose assessment was not found.
        """
        super().__init__(f"No risk assessment exists for auction {auction_id}")
