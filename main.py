"""Entry point of the Vankoo Risk Service API.

Assembles the application: registers every bounded context's router, the
exception handlers and the event handlers, starts the Kafka consumers (Investment's
auctions, Profile's certificates and Profile's verification requests), the delivery worker, the outbox relay and
the daily refresh of SUNAT's registries, and closes everything on shutdown. The schema is Alembic's
job (``alembic upgrade head``), never this module's.

Run it with one worker only: the consumer and the delivery worker live in
this process, and each extra worker would run its own. Scale by running more
containers in the same consumer group instead::

    fastapi dev main.py
    fastapi run main.py --workers 1
"""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from assessments.application.event_handlers import register_event_handlers as register_assessments_event_handlers
from assessments.application.services import RiskAssessmentApplicationService
from assessments.infrastructure.settings import investment_settings
from assessments.interfaces.consumers import AuctionLifecycleConsumer
from assessments.interfaces.dependencies import build_news_screener, build_risk_assessment_service
from assessments.interfaces.routes import mype_router as assessments_mype_router
from assessments.interfaces.routes import router as assessments_router
from assessments.interfaces.workers import EvaluationDeliveryWorker
from registries.infrastructure.settings import registry_settings
from registries.interfaces.scheduler import RegistryRefreshScheduler
from shared.application.events import event_bus
from shared.infrastructure.database import engine, session_factory
from shared.infrastructure.settings import kafka_settings, settings
from shared.interfaces.background import BackgroundTask
from shared.interfaces.exception_handlers import register_exception_handlers
from shared.interfaces.health import ReadinessCheck
from shared.interfaces.health import router as health_router
from shared.interfaces.outbox_relay import KafkaOutboxRelay
from sustainability.application.event_handlers import register_event_handlers as register_sustainability_event_handlers
from sustainability.application.services import GreenCertificationApplicationService
from sustainability.infrastructure.settings import green_settings
from sustainability.interfaces.consumers import ProfileEventsConsumer
from sustainability.interfaces.dependencies import (
    build_certificate_reader,
    build_documents_client,
    build_green_certification_service,
)
from verification.application.event_handlers import register_event_handlers as register_verification_event_handlers
from verification.application.services import CompanyVerificationApplicationService
from verification.infrastructure.settings import kyc_settings
from verification.interfaces.consumers import VerificationRequestsConsumer
from verification.interfaces.dependencies import build_company_verification_service, build_ruc_document_inspector

# Uvicorn configures its own loggers only; without this, the application's
# INFO messages (an event handler's, for one) are silently dropped.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
# aiokafka logs every rebalance and fetch at INFO; its warnings are enough.
logging.getLogger("aiokafka").setLevel(logging.WARNING)
# pyHanko logs, with a traceback, every certificate path it cannot build: the TSA
# timestamp of every ficha RUC, and a demo ficha checked against SUNAT's chain.
# The inspector logs what matters itself.
logging.getLogger("pyhanko").setLevel(logging.ERROR)
logging.getLogger("pyhanko_certvalidator").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shutdown work that must happen exactly once per process."""
    investment_client = httpx.AsyncClient(
        base_url=investment_settings.base_url,
        timeout=httpx.Timeout(investment_settings.read_timeout, connect=investment_settings.connect_timeout),
    )
    app.state.investment_client = investment_client
    news_screener, news_client = build_news_screener()
    app.state.news_screener = news_screener
    logging.getLogger(__name__).info(
        "News screening is %s", "on" if news_client is not None else "off (NEWS_ENABLED or OPENAI_API_KEY unset)"
    )

    def build_service(session: AsyncSession) -> RiskAssessmentApplicationService:
        return build_risk_assessment_service(session, investment_client, news_screener)

    certificate_reader, reader_client = build_certificate_reader()
    documents_client = build_documents_client()
    logging.getLogger(__name__).info(
        "Certificate reading is %s",
        "on" if reader_client is not None else "off (GREEN_ENABLED or OPENAI_API_KEY unset)",
    )

    def build_green_service(session: AsyncSession) -> GreenCertificationApplicationService:
        return build_green_certification_service(session, documents_client, certificate_reader)

    ruc_document_inspector = build_ruc_document_inspector()

    def build_verification_service(session: AsyncSession) -> CompanyVerificationApplicationService:
        return build_company_verification_service(session, documents_client, ruc_document_inspector)

    worker = EvaluationDeliveryWorker(session_factory, build_service)
    consumer = AuctionLifecycleConsumer(kafka_settings, session_factory, build_service)
    profile_consumer = ProfileEventsConsumer(
        kafka_settings,
        green_settings.profile_group_id,
        session_factory,
        build_green_service,
        green_settings.profile_offset_reset,
    )
    verification_consumer = VerificationRequestsConsumer(
        kafka_settings,
        kyc_settings.profile_group_id,
        session_factory,
        build_verification_service,
        kyc_settings.profile_offset_reset,
    )
    relay = KafkaOutboxRelay(kafka_settings, session_factory)
    register_assessments_event_handlers(event_bus, worker.wake)
    register_sustainability_event_handlers(event_bus, relay.wake)
    register_verification_event_handlers(event_bus, relay.wake)

    tasks: list[BackgroundTask] = []
    checks: dict[str, ReadinessCheck] = {}
    if kafka_settings.consumer_enabled:
        consumer_task = BackgroundTask("auction-lifecycle-consumer", consumer.run)
        tasks.append(consumer_task)
        checks["auction_lifecycle_consumer"] = lambda: consumer.ready
        tasks.append(BackgroundTask("profile-events-consumer", profile_consumer.run))
        checks["profile_events_consumer"] = lambda: profile_consumer.ready
        tasks.append(BackgroundTask("verification-requests-consumer", verification_consumer.run))
        checks["verification_requests_consumer"] = lambda: verification_consumer.ready
    if kafka_settings.producer_enabled:
        relay_task = BackgroundTask("outbox-relay", relay.run)
        tasks.append(relay_task)
        checks["outbox_relay"] = lambda: relay_task.running
    if investment_settings.delivery_enabled:
        delivery_task = BackgroundTask("evaluation-delivery", worker.run)
        tasks.append(delivery_task)
        checks["evaluation_delivery"] = lambda: delivery_task.running
    if registry_settings.refresh_enabled:
        # Not a readiness check: assessments work (graded C) while the padrón is loading.
        tasks.append(BackgroundTask("registry-refresh", RegistryRefreshScheduler(registry_settings).run))
    app.state.readiness_checks = checks

    for task in tasks:
        task.start()
    try:
        yield
    finally:
        for task in reversed(tasks):
            await task.stop()
        await investment_client.aclose()
        await documents_client.aclose()
        if reader_client is not None:
            await reader_client.close()
        if news_client is not None:
            await news_client.close()
        await engine.dispose()


def route_name_as_operation_id(route: APIRoute) -> str:
    """Use the route function's name as its OpenAPI ``operationId``."""
    return route.name


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    generate_unique_id_function=route_name_as_operation_id,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

register_exception_handlers(app)
app.include_router(health_router)
app.include_router(assessments_router)
app.include_router(assessments_mype_router)
