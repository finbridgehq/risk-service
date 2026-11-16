"""Dependency wiring of the Assessments bounded context.

The one place that chooses the concrete adapter for each port, the grading
policy, and the Registries facade the assessments ask about payers. The
consumer, the delivery worker and the routes all build the application
service through :func:`build_risk_assessment_service`.
"""
from typing import Annotated

import httpx
from fastapi import Depends, Request
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from assessments.application.acl import ExternalRegistriesService, ExternalSustainabilityService
from assessments.application.outbound_services import CreditBureau, NewsScreener
from assessments.application.services import RiskAssessmentApplicationService
from assessments.domain.services import PointsGradingPolicy, RiskGradingPolicy
from assessments.infrastructure.clients import HttpxAuctionEvaluationService
from assessments.infrastructure.credit_bureau import DisabledCreditBureau, SimulatedCreditBureau
from assessments.infrastructure.news import DisabledNewsScreener, OpenAINewsScreener
from assessments.infrastructure.repositories import (
    SqlAlchemyNewsScreeningRepository,
    SqlAlchemyRiskAssessmentRepository,
)
from assessments.infrastructure.settings import credit_bureau_settings, news_settings
from registries.interfaces.acl import RegistriesContextFacade
from shared.application.events import event_bus
from shared.infrastructure.messaging import SqlAlchemyInbox
from shared.interfaces.dependencies import SessionDep
from sustainability.interfaces.acl import SustainabilityContextFacade


def build_grading_policy() -> RiskGradingPolicy:
    """Return the policy that decides on auctions; see ``docs/SCORING_RULES.md``.

    Returns:
        RiskGradingPolicy: The policy in force.
    """
    return PointsGradingPolicy()


def build_credit_bureau() -> CreditBureau:
    """Return the credit bureau the scoring asks.

    SIMULATED: Vankoo has no bureau contract, so the one in force makes up a
    stable SBS rating per RUC. A real bureau's adapter goes here. See
    ``assessments/infrastructure/credit_bureau.py``.

    Returns:
        CreditBureau: The simulated bureau, or none if ``CREDIT_BUREAU_ENABLED`` is false.
    """
    return SimulatedCreditBureau() if credit_bureau_settings.enabled else DisabledCreditBureau()


def build_news_screener() -> tuple[NewsScreener, AsyncOpenAI | None]:
    """Return the news screener, and the OpenAI client it uses so the lifespan can close it.

    Returns:
        tuple[NewsScreener, AsyncOpenAI | None]: The OpenAI screener when
        ``NEWS_ENABLED`` and ``OPENAI_API_KEY`` are set, otherwise one that
        never searches (and no client).
    """
    if not news_settings.active or news_settings.api_key is None:
        return DisabledNewsScreener(), None
    client = AsyncOpenAI(api_key=news_settings.api_key.get_secret_value(), max_retries=1)
    return OpenAINewsScreener(client, news_settings), client


def build_risk_assessment_service(
    session: AsyncSession, investment_client: httpx.AsyncClient, news_screener: NewsScreener
) -> RiskAssessmentApplicationService:
    """Build the application service on one session.

    Args:
        session (AsyncSession): The session of the current unit of work.
        investment_client (httpx.AsyncClient): The process-wide client for Investment.
        news_screener (NewsScreener): The process-wide news screener.

    Returns:
        RiskAssessmentApplicationService: The service for this unit of work.
    """
    return RiskAssessmentApplicationService(
        SqlAlchemyRiskAssessmentRepository(session),
        SqlAlchemyInbox(session),
        ExternalRegistriesService(RegistriesContextFacade(session)),
        ExternalSustainabilityService(SustainabilityContextFacade(session)),
        build_credit_bureau(),
        news_screener,
        SqlAlchemyNewsScreeningRepository(session),
        HttpxAuctionEvaluationService(investment_client),
        build_grading_policy(),
        session,
        event_bus,
        news_cache_days=news_settings.cache_days,
    )


async def get_risk_assessment_service(request: Request, session: SessionDep) -> RiskAssessmentApplicationService:
    """Build the application service on the request's session.

    Args:
        request (Request): The current request; its application holds the Investment client.
        session (AsyncSession): The session of the current request.

    Returns:
        RiskAssessmentApplicationService: The service for this request.
    """
    client: httpx.AsyncClient = request.app.state.investment_client
    screener: NewsScreener = request.app.state.news_screener
    return build_risk_assessment_service(session, client, screener)


RiskAssessmentServiceDep = Annotated[RiskAssessmentApplicationService, Depends(get_risk_assessment_service)]
