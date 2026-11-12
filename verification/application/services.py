"""Application service of the Verification bounded context.

:class:`CompanyVerificationApplicationService` decides on every request of a
MYPE to be verified. It holds no rule: the checks are the policy's, and what
they add up to is the aggregate's.
"""
import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from shared.application.events import EventBus
from shared.application.messaging import Inbox
from shared.application.unit_of_work import UnitOfWork
from shared.domain.exceptions import DomainError
from verification.application.acl import ExternalRegistriesService
from verification.application.outbound_services import (
    CompanyVerificationPublisher,
    DocumentRejectedError,
    RucDocumentInspector,
    RucDocuments,
    TemporarilyUnavailableError,
)
from verification.domain.entities import CompanyVerification
from verification.domain.repositories import CompanyVerificationRepository
from verification.domain.services import KycPolicy
from verification.domain.value_objects import Applicant, Ruc, RucDocument, RucDocumentInspection

logger = logging.getLogger(__name__)

VERIFICATION_REQUESTED = "CompanyVerificationRequested"

type Clock = Callable[[], datetime]
type Today = Callable[[], date]


def utc_now() -> datetime:
    """Return the current time in UTC; the default clock."""
    return datetime.now(UTC)


class CompanyVerificationApplicationService:
    """Decides on the requests of MYPEs to be verified."""

    def __init__(
        self,
        repository: CompanyVerificationRepository,
        inbox: Inbox,
        documents: RucDocuments,
        inspector: RucDocumentInspector,
        registries: ExternalRegistriesService,
        publisher: CompanyVerificationPublisher,
        policy: KycPolicy,
        unit_of_work: UnitOfWork,
        event_bus: EventBus,
        today: Today,
        clock: Clock = utc_now,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            repository (CompanyVerificationRepository): Access to decisions.
            inbox (Inbox): The integration events already applied.
            documents (RucDocuments): Where the uploaded fichas are.
            inspector (RucDocumentInspector): Checks a ficha's signature and reads it.
            registries (ExternalRegistriesService): SUNAT's padrón and the sanction lists.
            publisher (CompanyVerificationPublisher): Tells Profile the decision.
            policy (KycPolicy): The ``kyc-v1`` checks.
            unit_of_work (UnitOfWork): The transaction to commit.
            event_bus (EventBus): Where the recorded domain events are published.
            today (Today): Today's date in Lima, the day a ficha's age is counted on.
            clock (Clock): The current time, replaceable in tests.
        """
        self._repository = repository
        self._inbox = inbox
        self._documents = documents
        self._inspector = inspector
        self._registries = registries
        self._publisher = publisher
        self._policy = policy
        self._unit_of_work = unit_of_work
        self._event_bus = event_bus
        self._today = today
        self._clock = clock

    async def verify_company(
        self,
        *,
        event_id: str,
        request_id: str,
        company_id: str,
        user_id: str,
        ruc: str,
        business_name: str,
        object_key: str,
        requested_at: datetime,
    ) -> CompanyVerification | None:
        """Check a MYPE's ficha RUC and its standing, and queue the decision for Profile.

        The decision, the processed event and the outgoing message are committed
        together, so a redelivered event never decides twice and a decision is
        never lost before it reaches Profile.

        Returns:
            CompanyVerification | None: The decision, the one already made for
            this request, or ``None`` if the event was already applied.

        Raises:
            DomainError: If a fact is not acceptable (a RUC that is not 11
                digits, a key outside the company's ``ruc`` folder…).
            TemporarilyUnavailableError: If the storage did not answer or the
                padrón or the SSCO list was never loaded; nothing was stored,
                and the event can be applied again.
        """
        if await self._inbox.has_processed(event_id):
            logger.info("Event %s was already applied; skipping it", event_id)
            return None
        applicant = Applicant(company_id=company_id, user_id=user_id, ruc=Ruc(ruc), business_name=business_name)
        document = RucDocument(object_key)
        if requested_at.tzinfo is None:
            raise DomainError("Request time must carry a time zone")

        existing = await self._repository.find_by_request_id(request_id)
        if existing is not None:
            await self._inbox.record(event_id, VERIFICATION_REQUESTED, company_id)
            await self._unit_of_work.commit()
            return existing

        today = self._today()
        standing = await self._registries.taxpayer_standing(applicant.ruc, today)
        if not standing.registry_loaded or not standing.shell_registry_loaded:
            raise TemporarilyUnavailableError("SUNAT's padrón or SSCO list was never loaded; waiting for it")
        inspection = await self._inspect(document)
        assessment = self._policy.evaluate(applicant, inspection, standing, today)
        verification = CompanyVerification.decide(
            request_id=request_id,
            applicant=applicant,
            document=document,
            requested_at=requested_at,
            facts=inspection.facts,
            assessment=assessment,
            source_event_id=event_id,
            now=self._clock(),
        )
        events = verification.pull_events()
        saved = await self._repository.save(verification)
        await self._publisher.publish_decided(saved)
        await self._inbox.record(event_id, VERIFICATION_REQUESTED, company_id)
        await self._unit_of_work.commit()
        await self._event_bus.publish(events)
        logger.info(
            "Company %s is %s%s: %s",
            company_id,
            saved.decision,
            " (demo)" if saved.demo else "",
            ", ".join(f"{result.code}={'ok' if result.passed else 'no'}" for result in saved.checks),
        )
        return saved

    async def _inspect(self, document: RucDocument) -> RucDocumentInspection:
        try:
            content = await self._documents.fetch(document)
        except DocumentRejectedError as error:
            return RucDocumentInspection.unusable(str(error))
        return await asyncio.to_thread(self._inspector.inspect, content)
