"""Application service of the Assessments bounded context.

Each method is one use case: it turns primitives into domain types, loads what
it needs, asks the aggregate to act, saves it and commits. It holds no
business rule: the decision is the policy's call, and what a delivery outcome
means for the assessment is the aggregate's.
"""
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from assessments.application.acl import ExternalRegistriesService, ExternalSustainabilityService
from assessments.application.outbound_services import (
    AuctionEvaluationService,
    CreditBureau,
    EvaluationOutcomeKind,
    InvestmentUnavailableError,
    NewsScreener,
    NewsUnavailableError,
)
from assessments.domain.entities import RiskAssessment
from assessments.domain.exceptions import RiskAssessmentNotFoundError
from assessments.domain.repositories import NewsScreeningRepository, RiskAssessmentRepository
from assessments.domain.services import RiskGradingPolicy
from assessments.domain.value_objects import (
    AssessmentId,
    AuctionFacts,
    AuctionId,
    Currency,
    GreenCheck,
    Money,
    NewsCheck,
    NewsCheckStatus,
    Payer,
    Ruc,
)
from shared.application.events import EventBus
from shared.application.messaging import Inbox
from shared.application.unit_of_work import UnitOfWork
from shared.domain.calendar import lima_date
from shared.domain.exceptions import DomainError

logger = logging.getLogger(__name__)

AUCTION_CREATED = "AuctionCreated"

type Clock = Callable[[], datetime]

NEWS_CACHE_DAYS = 7


def utc_now() -> datetime:
    """Return the current time in UTC; the default clock."""
    return datetime.now(UTC)


class RiskAssessmentApplicationService:
    """Use cases that issue risk assessments, deliver them and read them."""

    def __init__(
        self,
        risk_assessment_repository: RiskAssessmentRepository,
        inbox: Inbox,
        registries: ExternalRegistriesService,
        sustainability: ExternalSustainabilityService,
        credit_bureau: CreditBureau,
        news_screener: NewsScreener,
        news_screenings: NewsScreeningRepository,
        evaluation_service: AuctionEvaluationService,
        grading_policy: RiskGradingPolicy,
        unit_of_work: UnitOfWork,
        event_bus: EventBus,
        clock: Clock = utc_now,
        news_cache_days: int = NEWS_CACHE_DAYS,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            risk_assessment_repository (RiskAssessmentRepository): Access to assessments.
            inbox (Inbox): The integration events already applied.
            registries (ExternalRegistriesService): What the public registries say about the payer.
            sustainability (ExternalSustainabilityService): Whether the MYPE is green.
            credit_bureau (CreditBureau): The payer's credit rating (simulated today).
            news_screener (NewsScreener): Searches the web for negative news about the payer.
            news_screenings (NewsScreeningRepository): Recent searches, reused instead of searching again.
            evaluation_service (AuctionEvaluationService): Delivers decisions to Investment.
            grading_policy (RiskGradingPolicy): Decides eligibility and the grade.
            unit_of_work (UnitOfWork): The transaction to commit.
            event_bus (EventBus): Where the recorded domain events are published.
            clock (Clock): The current time, replaceable in tests.
            news_cache_days (int): How long a payer's news search is reused.
        """
        self._risk_assessments = risk_assessment_repository
        self._inbox = inbox
        self._registries = registries
        self._sustainability = sustainability
        self._credit_bureau = credit_bureau
        self._news_screener = news_screener
        self._news_screenings = news_screenings
        self._news_cache = timedelta(days=news_cache_days)
        self._evaluations = evaluation_service
        self._grading_policy = grading_policy
        self._unit_of_work = unit_of_work
        self._event_bus = event_bus
        self._clock = clock

    async def assess_auction(
        self,
        *,
        event_id: str,
        auction_id: str,
        invoice_id: str,
        mype_id: str,
        payer_ruc: str,
        payer_name: str,
        due_date: date,
        invoice_amount: Decimal,
        currency: str,
        green_certified: bool,
    ) -> RiskAssessment | None:
        """Grade an auction Investment has just created, once per auction.

        The assessment and the processed event are committed together, so a
        redelivered event never produces a second assessment.

        Returns:
            RiskAssessment | None: The new assessment, the one the auction
            already had, or ``None`` if this event was already applied.

        Raises:
            DomainError: If a fact is not acceptable (a RUC that is not 11
                digits, an unknown currency, a negative amount…).
        """
        if await self._inbox.has_processed(event_id):
            logger.info("Event %s was already applied; skipping it", event_id)
            return None

        facts = AuctionFacts(
            auction_id=AuctionId(auction_id),
            invoice_id=invoice_id,
            mype_id=mype_id,
            payer=Payer(Ruc(payer_ruc), payer_name),
            due_date=due_date,
            invoice_amount=Money(invoice_amount, self._currency(currency)),
            green_certified=green_certified,
        )

        existing = await self._risk_assessments.find_by_auction_id(facts.auction_id)
        if existing is not None:
            await self._inbox.record(event_id, AUCTION_CREATED, facts.auction_id.value)
            await self._unit_of_work.commit()
            logger.info("Auction %s already has assessment %s", auction_id, existing.assessment_id.value)
            return existing

        standing = await self._registries.payer_standing(facts.payer.ruc)
        credit = await self._credit_bureau.report(facts.payer.ruc)
        now = self._clock()
        news = await self._check_news(facts.payer.ruc, standing.name or facts.payer.name, now)
        decision = self._grading_policy.grade(facts, standing, credit, news, now.date())
        green = (
            await self._sustainability.green_check(facts.mype_id, lima_date(now))
            if decision.eligible
            else GreenCheck.not_checked()
        )
        assessment = RiskAssessment.issue(AssessmentId.new(), facts, decision, event_id, now, green)
        events = assessment.pull_events()
        saved = await self._risk_assessments.save(assessment)
        await self._inbox.record(event_id, AUCTION_CREATED, facts.auction_id.value)
        await self._unit_of_work.commit()
        await self._event_bus.publish(events)

        if decision.eligible:
            logger.info(
                "Auction %s graded %s (score %s, green %s, assessment %s)",
                auction_id,
                decision.grade,
                decision.score,
                green.status,
                saved.assessment_id.value,
            )
        else:
            logger.warning(
                "Auction %s is not eligible (%s, assessment %s): %s",
                auction_id,
                decision.rejection_code,
                saved.assessment_id.value,
                decision.rejection_reason,
            )
        return saved

    async def _check_news(self, ruc: Ruc, name: str, now: datetime) -> NewsCheck:
        cached = await self._news_screenings.find_since(ruc.value, now - self._news_cache)
        if cached is not None:
            return NewsCheck(NewsCheckStatus.SCREENED, cached)
        try:
            screening = await self._news_screener.screen(ruc, name)
        except NewsUnavailableError as error:
            logger.warning("News search for %s failed; assessing without it: %s", ruc.value, error)
            return NewsCheck(NewsCheckStatus.UNAVAILABLE)
        if screening is None:
            return NewsCheck(NewsCheckStatus.NOT_SCREENED)
        await self._news_screenings.save(screening)
        logger.info(
            "News search for %s: %d finding(s) from %d source(s)",
            ruc.value,
            len(screening.findings),
            screening.sources_consulted,
        )
        return NewsCheck(NewsCheckStatus.SCREENED, screening)

    async def deliver_assessment(self, auction_id: str) -> RiskAssessment:
        """Send an auction's pending decision to Investment and record the answer.

        An eligible decision becomes the auction's grade, with the certificate
        that makes it green when there is one; one that is not eligible
        rejects the auction.

        Returns:
            RiskAssessment: The assessment after the attempt.

        Raises:
            RiskAssessmentNotFoundError: If the auction has no assessment.
            ConflictError: If the delivery is already settled.
        """
        assessment = await self.get_risk_assessment_by_auction_id(auction_id)
        decision = assessment.decision
        try:
            if decision.eligible and decision.grade is not None:
                outcome = await self._evaluations.submit(
                    auction_id=assessment.facts.auction_id.value,
                    assessment_id=assessment.assessment_id.value,
                    risk_grade=decision.grade.value,
                    full_balance_outstanding=decision.full_balance_outstanding,
                    assessed_at=assessment.assessed_at,
                    green_certificate=assessment.green.certificate,
                )
            else:
                outcome = await self._evaluations.reject(
                    auction_id=assessment.facts.auction_id.value,
                    assessment_id=assessment.assessment_id.value,
                    reason_code=decision.rejection_code or "NOT_ELIGIBLE",
                    reason=decision.rejection_reason or "The invoice is not eligible",
                    assessed_at=assessment.assessed_at,
                )
        except InvestmentUnavailableError as error:
            assessment.record_delivery_failure(str(error), self._clock())
            logger.warning(
                "Could not deliver assessment %s (attempt %d), retrying at %s: %s",
                assessment.assessment_id.value,
                assessment.delivery_attempts,
                assessment.next_delivery_at,
                error,
            )
        else:
            if outcome.kind is EvaluationOutcomeKind.ACCEPTED:
                assessment.mark_delivered(self._clock(), outcome.auction_status or "")
                logger.info(
                    "Assessment %s delivered; auction %s is %s",
                    assessment.assessment_id.value,
                    auction_id,
                    outcome.auction_status,
                )
            else:
                assessment.mark_rejected(outcome.message or "Investment refused the evaluation")
                logger.error(
                    "Investment refused assessment %s for auction %s: %s",
                    assessment.assessment_id.value,
                    auction_id,
                    outcome.message,
                )

        saved = await self._risk_assessments.save(assessment)
        await self._unit_of_work.commit()
        return saved

    async def get_assessments_due_for_delivery(self, limit: int) -> list[RiskAssessment]:
        """Return the pending assessments whose next delivery is due, oldest first."""
        return await self._risk_assessments.find_due_for_delivery(self._clock(), limit)

    async def get_risk_assessment_by_auction_id(self, auction_id: str) -> RiskAssessment:
        """Return the assessment of one auction.

        Raises:
            RiskAssessmentNotFoundError: If the auction was never assessed.
            DomainError: If the auction id is blank or too long.
        """
        assessment = await self._risk_assessments.find_by_auction_id(AuctionId(auction_id))
        if assessment is None:
            raise RiskAssessmentNotFoundError(auction_id)
        return assessment

    async def get_mype_risk_assessment(self, auction_id: str, mype_id: str) -> RiskAssessment:
        """Return the assessment of one auction, for the MYPE that sells its invoice.

        Another MYPE's auction reads exactly like one that was never assessed, so
        the API does not confirm that the id exists.

        Raises:
            RiskAssessmentNotFoundError: If the auction was never assessed, or is another MYPE's.
            DomainError: If the auction id is blank or too long.
        """
        assessment = await self.get_risk_assessment_by_auction_id(auction_id)
        if assessment.facts.mype_id != mype_id:
            raise RiskAssessmentNotFoundError(auction_id)
        return assessment

    @staticmethod
    def _currency(code: str) -> Currency:
        try:
            return Currency(code.strip().upper())
        except ValueError:
            raise DomainError(f"'{code}' is not a supported currency: use PEN or USD") from None
