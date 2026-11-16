"""SQLAlchemy implementation of the Assessments repository port.

The repository is the only place that knows both the aggregate and its table:
it maps one to the other in both directions, so neither has to know about the
other.
"""
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assessments.domain.entities import RiskAssessment
from assessments.domain.repositories import NewsScreeningRepository, RiskAssessmentRepository
from assessments.domain.value_objects import (
    AssessmentId,
    AuctionFacts,
    AuctionId,
    Currency,
    DeliveryStatus,
    GradingDecision,
    GreenCertificate,
    GreenCheck,
    GreenCriterion,
    GreenStatus,
    Money,
    NewsCategory,
    NewsFinding,
    NewsScreening,
    NewsSeverity,
    Payer,
    RiskGrade,
    Ruc,
    ScoreFactor,
)
from assessments.infrastructure.models import NewsScreeningModel, RiskAssessmentModel


class SqlAlchemyRiskAssessmentRepository(RiskAssessmentRepository):
    """Stores :class:`RiskAssessment` aggregates in the ``risk_assessments`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def save(self, risk_assessment: RiskAssessment) -> RiskAssessment:
        model = await self._session.merge(self._to_model(risk_assessment))
        await self._session.flush()
        return self._to_entity(model)

    async def find_by_auction_id(self, auction_id: AuctionId) -> RiskAssessment | None:
        model = await self._session.scalar(
            select(RiskAssessmentModel).where(RiskAssessmentModel.auction_id == auction_id.value)
        )
        return self._to_entity(model) if model else None

    async def find_due_for_delivery(self, now: datetime, limit: int) -> list[RiskAssessment]:
        models = await self._session.scalars(
            select(RiskAssessmentModel)
            .where(
                RiskAssessmentModel.delivery_status == DeliveryStatus.PENDING.value,
                RiskAssessmentModel.next_delivery_at <= now,
            )
            .order_by(RiskAssessmentModel.next_delivery_at, RiskAssessmentModel.id)
            .limit(limit)
        )
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_model(assessment: RiskAssessment) -> RiskAssessmentModel:
        facts = assessment.facts
        decision = assessment.decision
        return RiskAssessmentModel(
            id=assessment.id,
            assessment_id=assessment.assessment_id.value,
            auction_id=facts.auction_id.value,
            invoice_id=facts.invoice_id,
            mype_id=facts.mype_id,
            payer_ruc=facts.payer.ruc.value,
            payer_name=facts.payer.name,
            due_date=facts.due_date,
            invoice_amount=facts.invoice_amount.amount,
            invoice_currency=facts.invoice_amount.currency.value,
            green_certified=facts.green_certified,
            green_status=assessment.green.status.value,
            green_certificate=_certificate_to_json(assessment.green.certificate),
            eligible=decision.eligible,
            risk_grade=decision.grade.value if decision.grade is not None else None,
            score=decision.score,
            score_factors=[
                {"code": factor.code, "points": factor.points, "detail": factor.detail} for factor in decision.factors
            ],
            rejection_code=decision.rejection_code,
            rejection_reason=decision.rejection_reason,
            full_balance_outstanding=decision.full_balance_outstanding,
            grading_policy=decision.policy_version,
            provisional=decision.provisional,
            assessed_at=assessment.assessed_at,
            source_event_id=assessment.source_event_id,
            delivery_status=assessment.delivery_status.value,
            delivery_attempts=assessment.delivery_attempts,
            next_delivery_at=assessment.next_delivery_at,
            last_delivery_error=assessment.last_delivery_error,
            delivered_at=assessment.delivered_at,
            investment_auction_status=assessment.investment_auction_status,
        )

    @staticmethod
    def _to_entity(model: RiskAssessmentModel) -> RiskAssessment:
        return RiskAssessment(
            AssessmentId(model.assessment_id),
            AuctionFacts(
                auction_id=AuctionId(model.auction_id),
                invoice_id=model.invoice_id,
                mype_id=model.mype_id,
                payer=Payer(Ruc(model.payer_ruc), model.payer_name),
                due_date=model.due_date,
                invoice_amount=Money(model.invoice_amount, Currency(model.invoice_currency)),
                green_certified=model.green_certified,
            ),
            GradingDecision(
                eligible=model.eligible,
                grade=RiskGrade(model.risk_grade) if model.risk_grade is not None else None,
                score=model.score,
                factors=tuple(
                    ScoreFactor(str(item["code"]), int(item["points"]), str(item["detail"]))
                    for item in model.score_factors or []
                ),
                full_balance_outstanding=model.full_balance_outstanding,
                policy_version=model.grading_policy,
                provisional=model.provisional,
                rejection_code=model.rejection_code,
                rejection_reason=model.rejection_reason,
            ),
            model.assessed_at,
            model.source_event_id,
            green=GreenCheck(
                GreenStatus(model.green_status or GreenStatus.NOT_CHECKED.value),
                _certificate_from_json(model.green_certificate),
            ),
            delivery_status=DeliveryStatus(model.delivery_status),
            delivery_attempts=model.delivery_attempts,
            next_delivery_at=model.next_delivery_at,
            last_delivery_error=model.last_delivery_error,
            delivered_at=model.delivered_at,
            investment_auction_status=model.investment_auction_status,
            id=model.id,
        )


class SqlAlchemyNewsScreeningRepository(NewsScreeningRepository):
    """Keeps each payer's latest news search in the ``news_screenings`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def find_since(self, ruc: str, since: datetime) -> NewsScreening | None:
        model = await self._session.get(NewsScreeningModel, ruc)
        if model is None or model.screened_at < since:
            return None
        return NewsScreening(
            ruc=model.ruc,
            findings=tuple(_finding_from_json(item) for item in model.findings or []),
            screened_at=model.screened_at,
            model=model.model,
            sources_consulted=model.sources_consulted,
        )

    async def save(self, screening: NewsScreening) -> None:
        await self._session.merge(
            NewsScreeningModel(
                ruc=screening.ruc,
                screened_at=screening.screened_at,
                model=screening.model,
                sources_consulted=screening.sources_consulted,
                findings=[_finding_to_json(finding) for finding in screening.findings],
            )
        )
        await self._session.flush()


def _finding_to_json(finding: NewsFinding) -> dict[str, Any]:
    return {
        "category": finding.category.value,
        "severity": finding.severity.value,
        "headline": finding.headline,
        "url": finding.url,
        "published_on": finding.published_on.isoformat() if finding.published_on else None,
        "summary": finding.summary,
    }


def _finding_from_json(item: dict[str, Any]) -> NewsFinding:
    published = item.get("published_on")
    return NewsFinding(
        category=NewsCategory(item["category"]),
        severity=NewsSeverity(item["severity"]),
        headline=str(item["headline"]),
        url=str(item["url"]),
        published_on=date.fromisoformat(published) if published else None,
        summary=str(item.get("summary") or ""),
    )


def _certificate_to_json(certificate: GreenCertificate | None) -> dict[str, Any] | None:
    if certificate is None:
        return None
    return {
        "certificationId": certificate.certification_id,
        "standard": certificate.standard,
        "issuer": certificate.issuer,
        "validUntil": certificate.valid_until.isoformat(),
        "criteria": [{"code": item.code, "detail": item.detail} for item in certificate.criteria],
    }


def _certificate_from_json(data: dict[str, Any] | None) -> GreenCertificate | None:
    if data is None:
        return None
    return GreenCertificate(
        certification_id=str(data["certificationId"]),
        standard=str(data["standard"]),
        issuer=str(data["issuer"]),
        valid_until=date.fromisoformat(str(data["validUntil"])),
        criteria=tuple(GreenCriterion(str(item["code"]), str(item["detail"])) for item in data["criteria"]),
    )
