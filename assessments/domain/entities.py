"""Aggregates of the Assessments bounded context."""
from datetime import datetime, timedelta

from assessments.domain.events import RiskAssessmentIssued
from assessments.domain.value_objects import (
    AssessmentId,
    AuctionFacts,
    DeliveryStatus,
    GradingDecision,
    GreenCheck,
    RiskGrade,
)
from shared.domain.entities import AggregateRoot
from shared.domain.exceptions import ConflictError, DomainError

MAX_RETRY_DELAY = timedelta(minutes=5)
DELIVERY_ERROR_MAX_LENGTH = 500
INVESTMENT_STATUS_MAX_LENGTH = 40


class RiskAssessment(AggregateRoot):
    """The grade given to one auction, and whether Investment has received it.

    An assessment is issued once per auction, from the facts Investment
    published and the decision of a grading policy. It then waits to be
    delivered: Investment either accepts the grade, refuses it for good, or
    cannot be reached, in which case the next attempt waits twice as long as
    the last one, up to five minutes.

    Attributes:
        id (int | None): Identity assigned when the assessment is first saved.
        assessment_id (AssessmentId): The identifier Investment stores.
        facts (AuctionFacts): What the grade was decided from.
        decision (GradingDecision): The grade and the policy that gave it.
        green (GreenCheck): Whether the auction is green, from its MYPE's certificate.
        assessed_at (datetime): When the grade was decided, in UTC.
        source_event_id (str): The Kafka event the assessment came from.
        delivery_status (DeliveryStatus): Where the delivery to Investment is.
        delivery_attempts (int): How many times Investment was called.
        next_delivery_at (datetime | None): When to try again; ``None`` once settled.
        last_delivery_error (str | None): Why the last attempt did not succeed.
        delivered_at (datetime | None): When Investment accepted the grade.
        investment_auction_status (str | None): The auction's status Investment reported.
    """

    def __init__(
        self,
        assessment_id: AssessmentId,
        facts: AuctionFacts,
        decision: GradingDecision,
        assessed_at: datetime,
        source_event_id: str,
        *,
        green: GreenCheck | None = None,
        delivery_status: DeliveryStatus = DeliveryStatus.PENDING,
        delivery_attempts: int = 0,
        next_delivery_at: datetime | None = None,
        last_delivery_error: str | None = None,
        delivered_at: datetime | None = None,
        investment_auction_status: str | None = None,
        id: int | None = None,
    ) -> None:
        """Initialize an assessment; also the path the repository rebuilds one through.

        Raises:
            DomainError: If a timestamp has no time zone, the source event is
                blank or the attempt count is negative.
        """
        super().__init__()
        self._require_aware(assessed_at, "Assessment time")
        if next_delivery_at is not None:
            self._require_aware(next_delivery_at, "Next delivery time")
        if delivered_at is not None:
            self._require_aware(delivered_at, "Delivery time")
        if not source_event_id.strip():
            raise DomainError("An assessment must name the event it came from")
        if delivery_attempts < 0:
            raise DomainError("Delivery attempts cannot be negative")
        self._id = id
        self._assessment_id = assessment_id
        self._facts = facts
        self._decision = decision
        self._green = green or GreenCheck.not_checked()
        self._assessed_at = assessed_at
        self._source_event_id = source_event_id.strip()
        self._delivery_status = delivery_status
        self._delivery_attempts = delivery_attempts
        self._next_delivery_at = next_delivery_at
        self._last_delivery_error = last_delivery_error
        self._delivered_at = delivered_at
        self._investment_auction_status = investment_auction_status

    @classmethod
    def issue(
        cls,
        assessment_id: AssessmentId,
        facts: AuctionFacts,
        decision: GradingDecision,
        source_event_id: str,
        now: datetime,
        green: GreenCheck | None = None,
    ) -> "RiskAssessment":
        """Decide on an auction and schedule the delivery of the decision right away.

        Args:
            assessment_id (AssessmentId): A fresh identifier.
            facts (AuctionFacts): What Investment published about the auction.
            decision (GradingDecision): What the grading policy concluded.
            source_event_id (str): The Kafka event the facts came from.
            now (datetime): The current time, in UTC.
            green (GreenCheck | None): Whether the auction is green; not checked
                when it is not eligible.

        Returns:
            RiskAssessment: The new assessment, with ``RiskAssessmentIssued`` recorded.

        Raises:
            DomainError: If ``now`` has no time zone.
        """
        if green is not None and green.green and not decision.eligible:
            raise DomainError("An auction that is not eligible cannot be green")
        assessment = cls(assessment_id, facts, decision, now, source_event_id, green=green, next_delivery_at=now)
        assessment.record_event(
            RiskAssessmentIssued(
                auction_id=facts.auction_id.value,
                assessment_id=assessment_id.value,
                risk_grade=decision.grade.value if decision.grade is not None else None,
            )
        )
        return assessment

    @property
    def id(self) -> int | None:
        """Identity assigned by the first save; ``None`` before it."""
        return self._id

    @property
    def assessment_id(self) -> AssessmentId:
        """The identifier Investment stores with the grade."""
        return self._assessment_id

    @property
    def facts(self) -> AuctionFacts:
        """What the grade was decided from."""
        return self._facts

    @property
    def decision(self) -> GradingDecision:
        """The grade and the policy that gave it."""
        return self._decision

    @property
    def grade(self) -> RiskGrade | None:
        """The risk class given to the auction; ``None`` if it is not eligible."""
        return self._decision.grade

    @property
    def green(self) -> GreenCheck:
        """Whether the auction is green, from its MYPE's certificate."""
        return self._green

    @property
    def eligible(self) -> bool:
        """Whether the invoice can be funded at all."""
        return self._decision.eligible

    @property
    def assessed_at(self) -> datetime:
        """When the grade was decided."""
        return self._assessed_at

    @property
    def source_event_id(self) -> str:
        """The Kafka event the assessment came from."""
        return self._source_event_id

    @property
    def delivery_status(self) -> DeliveryStatus:
        """Where the delivery to Investment is."""
        return self._delivery_status

    @property
    def delivery_attempts(self) -> int:
        """How many times Investment was called."""
        return self._delivery_attempts

    @property
    def next_delivery_at(self) -> datetime | None:
        """When to try the delivery again; ``None`` once it is settled."""
        return self._next_delivery_at

    @property
    def last_delivery_error(self) -> str | None:
        """Why the last attempt did not succeed, if it did not."""
        return self._last_delivery_error

    @property
    def delivered_at(self) -> datetime | None:
        """When Investment accepted the grade."""
        return self._delivered_at

    @property
    def investment_auction_status(self) -> str | None:
        """The auction's status as Investment reported it on delivery."""
        return self._investment_auction_status

    def mark_delivered(self, now: datetime, investment_auction_status: str) -> None:
        """Record that Investment accepted the grade.

        Args:
            now (datetime): The current time, in UTC.
            investment_auction_status (str): The auction's status Investment returned.

        Raises:
            ConflictError: If the delivery is already settled.
            DomainError: If ``now`` has no time zone.
        """
        self._require_pending()
        self._require_aware(now, "Delivery time")
        self._delivery_attempts += 1
        self._delivery_status = DeliveryStatus.DELIVERED
        self._delivered_at = now
        self._next_delivery_at = None
        self._last_delivery_error = None
        self._investment_auction_status = investment_auction_status.strip()[:INVESTMENT_STATUS_MAX_LENGTH] or None

    def mark_rejected(self, reason: str) -> None:
        """Record that Investment refused the grade for good; it is not sent again.

        Args:
            reason (str): What Investment answered.

        Raises:
            ConflictError: If the delivery is already settled.
        """
        self._require_pending()
        self._delivery_attempts += 1
        self._delivery_status = DeliveryStatus.REJECTED
        self._next_delivery_at = None
        self._last_delivery_error = self._shorten(reason)

    def record_delivery_failure(self, error: str, now: datetime) -> None:
        """Record that Investment could not be reached, and schedule the next attempt.

        The wait doubles with each failure (1 s, 2 s, 4 s…) and never exceeds
        five minutes.

        Args:
            error (str): Why the attempt failed.
            now (datetime): The current time, in UTC.

        Raises:
            ConflictError: If the delivery is already settled.
            DomainError: If ``now`` has no time zone.
        """
        self._require_pending()
        self._require_aware(now, "Failure time")
        self._delivery_attempts += 1
        delay = min(timedelta(seconds=2 ** min(self._delivery_attempts - 1, 16)), MAX_RETRY_DELAY)
        self._next_delivery_at = now + delay
        self._last_delivery_error = self._shorten(error)

    def _require_pending(self) -> None:
        if self._delivery_status is not DeliveryStatus.PENDING:
            raise ConflictError(
                f"The delivery of assessment {self._assessment_id.value} is already {self._delivery_status}"
            )

    @staticmethod
    def _require_aware(moment: datetime, what: str) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise DomainError(f"{what} must carry a time zone")

    @staticmethod
    def _shorten(text: str) -> str:
        return (text.strip() or "No detail given")[:DELIVERY_ERROR_MAX_LENGTH]
