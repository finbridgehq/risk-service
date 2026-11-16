"""Outbound ports of the Assessments application layer.

A credit bureau reports a payer's rating in the financial system through
:class:`CreditBureau`; today the only adapter is a simulation. A
:class:`NewsScreener` searches the web for negative news about a payer.

The application service delivers each assessment to Investment through
:class:`AuctionEvaluationService`. It does not know that the other side is an
HTTP endpoint; it only knows the three things that can happen: Investment
accepts the grade, refuses it for good, or cannot be reached right now.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from assessments.domain.value_objects import CreditReport, GreenCertificate, NewsScreening, Ruc


class EvaluationOutcomeKind(StrEnum):
    """What Investment did with a grade."""

    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationOutcome:
    """Investment's final answer to a delivered grade.

    Attributes:
        kind (EvaluationOutcomeKind): Whether it accepted or refused the grade.
        auction_status (str | None): The auction's status after accepting it.
        message (str | None): Why it refused, in Investment's words.
    """

    kind: EvaluationOutcomeKind
    auction_status: str | None = None
    message: str | None = None


class CreditBureau(ABC):
    """A credit bureau (Equifax, Sentinel…) that reports a payer's rating in the financial system."""

    @abstractmethod
    async def report(self, ruc: Ruc) -> CreditReport | None:
        """Return the bureau's report on a payer, or ``None`` if there is none to give."""


class NewsUnavailableError(Exception):
    """The news search could not give an answer; the assessment goes on without it."""


class NewsScreener(ABC):
    """Searches the web for negative news about a payer (fraud, insolvency, lawsuits…)."""

    @abstractmethod
    async def screen(self, ruc: Ruc, name: str) -> NewsScreening | None:
        """Search for negative news about a company.

        Args:
            ruc (Ruc): The payer's RUC.
            name (str): Its name, as SUNAT registers it when known.

        Returns:
            NewsScreening | None: What was found (possibly nothing), or ``None``
            if screening is turned off.

        Raises:
            NewsUnavailableError: If the search failed or its answer was unusable.
        """


class InvestmentUnavailableError(Exception):
    """Investment could not be reached or failed; the delivery must be retried."""


class AuctionEvaluationService(ABC):
    """Delivers a decision to the auction it was made about, in Investment."""

    @abstractmethod
    async def submit(
        self,
        *,
        auction_id: str,
        assessment_id: str,
        risk_grade: str,
        full_balance_outstanding: bool,
        assessed_at: datetime,
        green_certificate: GreenCertificate | None = None,
    ) -> EvaluationOutcome:
        """Send the grade to Investment, and the certificate that makes the auction green, if any.

        Sending the same assessment again is safe: Investment ignores an
        assessment id it already applied with the same grade and certificate.

        Args:
            auction_id (str): The auction being graded.
            assessment_id (str): The assessment's identifier.
            risk_grade (str): ``A``, ``B`` or ``C``.
            full_balance_outstanding (bool): Whether the invoice is fully owed.
            assessed_at (datetime): When the grade was decided, in UTC.
            green_certificate (GreenCertificate | None): Present when the auction is green.

        Returns:
            EvaluationOutcome: Investment's final answer.

        Raises:
            InvestmentUnavailableError: If Investment could not give a final answer.
        """

    @abstractmethod
    async def reject(
        self,
        *,
        auction_id: str,
        assessment_id: str,
        reason_code: str,
        reason: str,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Tell Investment the invoice is not eligible, so the auction is rejected.

        Sending the same rejection again is safe: Investment ignores an
        assessment id it already applied with the same reason code.

        Args:
            auction_id (str): The auction being rejected.
            assessment_id (str): The assessment's identifier.
            reason_code (str): Why, as a stable code, e.g. ``PAYER_NOT_ACTIVE``.
            reason (str): Why, in words the MYPE can read.
            assessed_at (datetime): When the decision was made, in UTC.

        Returns:
            EvaluationOutcome: Investment's final answer.

        Raises:
            InvestmentUnavailableError: If Investment could not give a final answer.
        """
