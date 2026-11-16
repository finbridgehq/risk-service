"""In-memory stand-ins for the Verification ports."""

from dataclasses import dataclass, field
from typing import Any, cast

from registries.interfaces.acl import PayerStandingRecord
from shared.application.events import EventBus
from tests.fakes import FakeRegistriesFacade, FakeUnitOfWork, InMemoryInbox
from tests.green_fakes import InMemoryOutbox
from tests.kyc_data import (
    ACTIVE_TAXPAYER,
    BUSINESS_NAME,
    COMPANY_ID,
    NOW,
    OBJECT_KEY,
    REQUEST_ID,
    RUC,
    TODAY,
    USER_ID,
    signed_by_sunat,
)
from verification.application.acl import ExternalRegistriesService
from verification.application.outbound_services import RucDocumentInspector, RucDocuments
from verification.application.services import CompanyVerificationApplicationService
from verification.domain.entities import CompanyVerification
from verification.domain.repositories import CompanyVerificationRepository
from verification.domain.services import KycPolicy
from verification.domain.value_objects import RucDocument, RucDocumentInspection
from verification.infrastructure.publisher import OutboxCompanyVerificationPublisher


class InMemoryCompanyVerifications(CompanyVerificationRepository):
    """Keeps decisions in a list, assigning ids like the database would."""

    def __init__(self) -> None:
        self.rows: list[CompanyVerification] = []

    async def save(self, company_verification: CompanyVerification) -> CompanyVerification:
        stored = CompanyVerification(
            company_verification.verification_id,
            company_verification.request_id,
            company_verification.applicant,
            company_verification.document,
            company_verification.requested_at,
            company_verification.facts,
            company_verification.checks,
            company_verification.field_errors,
            company_verification.evidence,
            company_verification.demo,
            company_verification.decision,
            company_verification.decided_at,
            company_verification.rules_version,
            company_verification.source_event_id,
            id=len(self.rows) + 1,
        )
        self.rows.append(stored)
        return stored

    async def find_by_request_id(self, request_id: str) -> CompanyVerification | None:
        return next((row for row in self.rows if row.request_id == request_id), None)


@dataclass
class FakeRucDocuments(RucDocuments):
    """Returns the same bytes for every document, or raises the scripted failure."""

    failure: Exception | None = None
    fetched: list[str] = field(default_factory=list)

    async def fetch(self, document: RucDocument) -> bytes:
        self.fetched.append(document.object_key)
        if self.failure is not None:
            raise self.failure
        return b"%PDF-1.7 ficha"


@dataclass
class FakeInspector(RucDocumentInspector):
    """Answers every ficha with the same inspection."""

    inspection: RucDocumentInspection = field(default_factory=signed_by_sunat)
    inspections: int = 0

    def inspect(self, content: bytes) -> RucDocumentInspection:
        self.inspections += 1
        return self.inspection


@dataclass
class KycServiceUnderTest:
    """The application service wired to fakes, with the fakes at hand."""

    service: CompanyVerificationApplicationService
    repository: InMemoryCompanyVerifications
    inbox: InMemoryInbox
    documents: FakeRucDocuments
    inspector: FakeInspector
    outbox: InMemoryOutbox
    unit_of_work: FakeUnitOfWork
    event_bus: EventBus


def build_kyc_service(
    inspector: FakeInspector | None = None,
    documents: FakeRucDocuments | None = None,
    standing: PayerStandingRecord = ACTIVE_TAXPAYER,
) -> KycServiceUnderTest:
    """Wire the application service to fresh fakes and the ``kyc-v1`` rules."""
    repository = InMemoryCompanyVerifications()
    inbox = InMemoryInbox()
    fake_documents = documents or FakeRucDocuments()
    fake_inspector = inspector or FakeInspector()
    outbox = InMemoryOutbox()
    unit_of_work = FakeUnitOfWork()
    bus = EventBus()
    service = CompanyVerificationApplicationService(
        repository,
        inbox,
        fake_documents,
        fake_inspector,
        ExternalRegistriesService(cast(Any, FakeRegistriesFacade(standing))),
        OutboxCompanyVerificationPublisher(outbox),
        KycPolicy(),
        unit_of_work,
        bus,
        lambda: TODAY,
        lambda: NOW,
    )
    return KycServiceUnderTest(service, repository, inbox, fake_documents, fake_inspector, outbox, unit_of_work, bus)


def verification_requested(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for ``verify_company``, valid unless overridden."""
    arguments: dict[str, Any] = {
        "event_id": "71000000-0000-4000-8000-000000000001",
        "request_id": REQUEST_ID,
        "company_id": COMPANY_ID,
        "user_id": USER_ID,
        "ruc": RUC,
        "business_name": BUSINESS_NAME,
        "object_key": OBJECT_KEY,
        "requested_at": NOW,
    }
    arguments.update(overrides)
    return arguments
