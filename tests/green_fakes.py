"""In-memory stand-ins for the Sustainability ports."""

from dataclasses import dataclass, field
from typing import Any, cast

from registries.interfaces.acl import PayerStandingRecord
from shared.application.events import EventBus
from shared.application.outbox import Outbox, OutboxMessage
from sustainability.application.acl import ExternalRegistriesService
from sustainability.application.outbound_services import CertificateDocuments, CertificateReader
from sustainability.application.services import GreenCertificationApplicationService
from sustainability.domain.entities import GreenCertification
from sustainability.domain.repositories import GreenCertificationRepository
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.domain.value_objects import CertificateDocument, CertificateExtraction
from sustainability.infrastructure.publisher import OutboxGreenCertificationPublisher
from tests.fakes import FakeRegistriesFacade, FakeUnitOfWork, InMemoryInbox
from tests.green_data import COMPANY_ID, GREEN_MYPE, NOW, OBJECT_KEY, RUC, TODAY, USER_ID, iso_14001


class InMemoryGreenCertifications(GreenCertificationRepository):
    """Keeps decisions in a list, assigning ids like the database would."""

    def __init__(self) -> None:
        self.rows: list[GreenCertification] = []

    async def save(self, green_certification: GreenCertification) -> GreenCertification:
        stored = GreenCertification(
            green_certification.certification_id,
            green_certification.submission_id,
            green_certification.mype,
            green_certification.document,
            green_certification.submitted_at,
            green_certification.extraction,
            green_certification.criteria,
            green_certification.decision,
            green_certification.decided_at,
            green_certification.reader,
            green_certification.rules_version,
            green_certification.source_event_id,
            id=len(self.rows) + 1,
        )
        self.rows.append(stored)
        return stored

    async def find_by_submission_id(self, submission_id: str) -> GreenCertification | None:
        return next((row for row in self.rows if row.submission_id == submission_id), None)

    async def find_latest_by_user_id(self, user_id: str) -> GreenCertification | None:
        mine = [row for row in self.rows if row.mype.user_id == user_id]
        return max(mine, key=lambda row: (row.submitted_at, row.id or 0)) if mine else None


@dataclass
class FakeDocuments(CertificateDocuments):
    """Returns the same bytes for every document, or raises the scripted failure."""

    failure: Exception | None = None
    fetched: list[str] = field(default_factory=list)

    async def fetch(self, document: CertificateDocument) -> bytes:
        self.fetched.append(document.object_key)
        if self.failure is not None:
            raise self.failure
        return b"%PDF-1.7 certificate"


@dataclass
class FakeReader(CertificateReader):
    """Answers every document with the same extraction, or raises the scripted failure."""

    extraction: CertificateExtraction | Exception = field(default_factory=iso_14001)
    is_active: bool = True
    reads: int = 0

    @property
    def name(self) -> str:
        return "fake-reader"

    @property
    def active(self) -> bool:
        return self.is_active

    async def read(self, document: CertificateDocument, content: bytes) -> CertificateExtraction:
        self.reads += 1
        if isinstance(self.extraction, Exception):
            raise self.extraction
        return self.extraction


class InMemoryOutbox(Outbox):
    """Keeps queued messages in a list."""

    def __init__(self) -> None:
        self.messages: list[OutboxMessage] = []

    async def add(self, message: OutboxMessage) -> None:
        self.messages.append(message)


@dataclass
class GreenServiceUnderTest:
    """The application service wired to fakes, with the fakes at hand."""

    service: GreenCertificationApplicationService
    repository: InMemoryGreenCertifications
    inbox: InMemoryInbox
    documents: FakeDocuments
    reader: FakeReader
    outbox: InMemoryOutbox
    unit_of_work: FakeUnitOfWork
    event_bus: EventBus


def build_green_service(
    reader: FakeReader | None = None,
    documents: FakeDocuments | None = None,
    standing: PayerStandingRecord = GREEN_MYPE,
) -> GreenServiceUnderTest:
    """Wire the application service to fresh fakes and the ``green-v1`` rules."""
    repository = InMemoryGreenCertifications()
    inbox = InMemoryInbox()
    fake_documents = documents or FakeDocuments()
    fake_reader = reader or FakeReader()
    outbox = InMemoryOutbox()
    unit_of_work = FakeUnitOfWork()
    bus = EventBus()
    service = GreenCertificationApplicationService(
        repository,
        inbox,
        fake_documents,
        fake_reader,
        ExternalRegistriesService(cast(Any, FakeRegistriesFacade(standing))),
        OutboxGreenCertificationPublisher(outbox),
        GreenCertificationPolicy(),
        unit_of_work,
        bus,
        lambda: TODAY,
        lambda: NOW,
    )
    return GreenServiceUnderTest(service, repository, inbox, fake_documents, fake_reader, outbox, unit_of_work, bus)


def certificate_submitted(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for ``decide_on_certificate``, valid unless overridden."""
    arguments: dict[str, Any] = {
        "event_id": "70000000-0000-4000-8000-000000000001",
        "submission_id": "80000000-0000-4000-8000-000000000001",
        "company_id": COMPANY_ID,
        "user_id": USER_ID,
        "ruc": RUC,
        "business_name": "Agroexport Verde S.A.C.",
        "object_key": OBJECT_KEY,
        "content_type": "application/pdf",
        "submitted_at": NOW,
    }
    arguments.update(overrides)
    return arguments
