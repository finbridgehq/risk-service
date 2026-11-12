"""Dependency wiring of the Verification bounded context.

The one place that chooses the inspector, the storage adapter and the outbox the
decisions go through. The consumer builds the application service with
:func:`build_company_verification_service`.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from registries.interfaces.acl import RegistriesContextFacade
from shared.application.events import event_bus
from shared.domain.calendar import lima_today
from shared.infrastructure.messaging import SqlAlchemyInbox
from shared.infrastructure.outbox import SqlAlchemyOutbox
from verification.application.acl import ExternalRegistriesService
from verification.application.outbound_services import RucDocumentInspector
from verification.application.services import CompanyVerificationApplicationService
from verification.domain.services import KycPolicy
from verification.infrastructure.documents import HttpxRucDocuments
from verification.infrastructure.inspector import PdfRucDocumentInspector
from verification.infrastructure.publisher import OutboxCompanyVerificationPublisher
from verification.infrastructure.repositories import SqlAlchemyCompanyVerificationRepository
from verification.infrastructure.settings import kyc_settings

logger = logging.getLogger(__name__)


def build_ruc_document_inspector() -> RucDocumentInspector:
    """Return the process-wide inspector: SUNAT's pinned chain, plus the demo CA if ``KYC_DEMO_CA_PATH`` is set."""
    if kyc_settings.demo_ca_path is not None:
        logger.warning(
            "KYC_DEMO_CA_PATH is set: fichas signed by the demonstration CA are accepted and marked demo. "
            "Never set it in production."
        )
    return PdfRucDocumentInspector.pinned(kyc_settings.demo_ca_path)


def build_company_verification_service(
    session: AsyncSession, documents_client: httpx.AsyncClient, inspector: RucDocumentInspector
) -> CompanyVerificationApplicationService:
    """Build the application service on one session.

    Args:
        session (AsyncSession): The session of the current unit of work.
        documents_client (httpx.AsyncClient): The process-wide client for Profile's bucket.
        inspector (RucDocumentInspector): The process-wide inspector.

    Returns:
        CompanyVerificationApplicationService: The service for this unit of work.
    """
    return CompanyVerificationApplicationService(
        SqlAlchemyCompanyVerificationRepository(session),
        SqlAlchemyInbox(session),
        HttpxRucDocuments(documents_client, kyc_settings.max_bytes),
        inspector,
        ExternalRegistriesService(RegistriesContextFacade(session)),
        OutboxCompanyVerificationPublisher(SqlAlchemyOutbox(session)),
        KycPolicy(),
        session,
        event_bus,
        lima_today,
    )
