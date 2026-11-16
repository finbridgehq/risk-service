"""Dependency wiring of the Sustainability bounded context.

The one place that chooses the reader, the storage adapter and the outbox the
decisions go through. The consumer builds the application service with
:func:`build_green_certification_service`.
"""
import httpx
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from registries.interfaces.acl import RegistriesContextFacade
from shared.application.events import event_bus
from shared.domain.calendar import lima_today
from shared.infrastructure.messaging import SqlAlchemyInbox
from shared.infrastructure.outbox import SqlAlchemyOutbox
from sustainability.application.acl import ExternalRegistriesService
from sustainability.application.outbound_services import CertificateReader
from sustainability.application.services import GreenCertificationApplicationService
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.infrastructure.documents import HttpxCertificateDocuments
from sustainability.infrastructure.publisher import OutboxGreenCertificationPublisher
from sustainability.infrastructure.reader import DisabledCertificateReader, OpenAICertificateReader
from sustainability.infrastructure.repositories import SqlAlchemyGreenCertificationRepository
from sustainability.infrastructure.settings import green_settings


def build_certificate_reader() -> tuple[CertificateReader, AsyncOpenAI | None]:
    """Return the certificate reader, and the OpenAI client it uses so the lifespan can close it.

    Returns:
        tuple[CertificateReader, AsyncOpenAI | None]: The OpenAI reader when
        ``GREEN_ENABLED`` and ``OPENAI_API_KEY`` are set, otherwise one that
        never reads (and no client).
    """
    if not green_settings.active or green_settings.api_key is None:
        return DisabledCertificateReader(), None
    client = AsyncOpenAI(api_key=green_settings.api_key.get_secret_value(), max_retries=1)
    return OpenAICertificateReader(client, green_settings), client


def build_documents_client() -> httpx.AsyncClient:
    """Return the process-wide client for Profile's bucket."""
    return httpx.AsyncClient(
        base_url=green_settings.documents_base_url.rstrip("/") + "/", timeout=httpx.Timeout(30.0, connect=5.0)
    )


def build_green_certification_service(
    session: AsyncSession, documents_client: httpx.AsyncClient, reader: CertificateReader
) -> GreenCertificationApplicationService:
    """Build the application service on one session.

    Args:
        session (AsyncSession): The session of the current unit of work.
        documents_client (httpx.AsyncClient): The process-wide client for the bucket.
        reader (CertificateReader): The process-wide certificate reader.

    Returns:
        GreenCertificationApplicationService: The service for this unit of work.
    """
    return GreenCertificationApplicationService(
        SqlAlchemyGreenCertificationRepository(session),
        SqlAlchemyInbox(session),
        HttpxCertificateDocuments(documents_client, green_settings.max_bytes),
        reader,
        ExternalRegistriesService(RegistriesContextFacade(session)),
        OutboxGreenCertificationPublisher(SqlAlchemyOutbox(session)),
        GreenCertificationPolicy(),
        session,
        event_bus,
        lima_today,
    )
