"""Application services of the Sustainability bounded context.

:class:`GreenCertificationApplicationService` decides on every certificate a
MYPE uploads; :class:`GreenCertificationQueryService` answers whether a MYPE is
green on a given day. Neither holds a rule: the checks are the policy's, and
what they add up to is the aggregate's.
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from shared.application.events import EventBus
from shared.application.messaging import Inbox
from shared.application.unit_of_work import UnitOfWork
from shared.domain.exceptions import DomainError
from sustainability.application.acl import ExternalRegistriesService
from sustainability.application.outbound_services import (
    CertificateDocuments,
    CertificateReader,
    CertificateUnreadableError,
    DocumentRejectedError,
    GreenCertificationPublisher,
)
from sustainability.domain.entities import GreenCertification
from sustainability.domain.repositories import GreenCertificationRepository
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.domain.value_objects import (
    CertificateDocument,
    CertificateExtraction,
    DocumentType,
    GreenStatusCode,
    Mype,
    Ruc,
)

logger = logging.getLogger(__name__)

CERTIFICATE_SUBMITTED = "SustainabilityCertificateSubmitted"

type Clock = Callable[[], datetime]
type Today = Callable[[], date]


def utc_now() -> datetime:
    """Return the current time in UTC; the default clock."""
    return datetime.now(UTC)


class GreenCertificationApplicationService:
    """Decides on the certificates MYPEs upload."""

    def __init__(
        self,
        repository: GreenCertificationRepository,
        inbox: Inbox,
        documents: CertificateDocuments,
        reader: CertificateReader,
        registries: ExternalRegistriesService,
        publisher: GreenCertificationPublisher,
        policy: GreenCertificationPolicy,
        unit_of_work: UnitOfWork,
        event_bus: EventBus,
        today: Today,
        clock: Clock = utc_now,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            repository (GreenCertificationRepository): Access to decisions.
            inbox (Inbox): The integration events already applied.
            documents (CertificateDocuments): Where the uploaded files are.
            reader (CertificateReader): Extracts a certificate's facts.
            registries (ExternalRegistriesService): SUNAT's name and OEFA's register.
            publisher (GreenCertificationPublisher): Tells Profile the decision.
            policy (GreenCertificationPolicy): The ``green-v1`` checks.
            unit_of_work (UnitOfWork): The transaction to commit.
            event_bus (EventBus): Where the recorded domain events are published.
            today (Today): Today's date in Lima, the day a certificate must be in force.
            clock (Clock): The current time, replaceable in tests.
        """
        self._repository = repository
        self._inbox = inbox
        self._documents = documents
        self._reader = reader
        self._registries = registries
        self._publisher = publisher
        self._policy = policy
        self._unit_of_work = unit_of_work
        self._event_bus = event_bus
        self._today = today
        self._clock = clock

    async def decide_on_certificate(
        self,
        *,
        event_id: str,
        submission_id: str,
        company_id: str,
        user_id: str,
        ruc: str,
        business_name: str,
        object_key: str,
        content_type: str,
        submitted_at: datetime,
    ) -> GreenCertification | None:
        """Read a certificate a MYPE uploaded, check it and queue the decision for Profile.

        The decision, the processed event and the outgoing message are committed
        together, so a redelivered event never decides twice and a decision is
        never lost before it reaches Profile.

        Returns:
            GreenCertification | None: The decision, the one already made for
            this upload, or ``None`` if the event was already applied or there
            is no reader to decide with.

        Raises:
            DomainError: If a fact is not acceptable (a RUC that is not 11
                digits, a key outside the sustainability folder…).
            TemporarilyUnavailableError: If the storage or the reader did not
                answer; nothing was stored, and the event can be applied again.
        """
        if await self._inbox.has_processed(event_id):
            logger.info("Event %s was already applied; skipping it", event_id)
            return None
        mype = Mype(company_id=company_id, user_id=user_id, ruc=Ruc(ruc), business_name=business_name)
        document = CertificateDocument(object_key, self._document_type(content_type))
        if submitted_at.tzinfo is None:
            raise DomainError("Submission time must carry a time zone")

        existing = await self._repository.find_by_submission_id(submission_id)
        if existing is not None:
            await self._inbox.record(event_id, CERTIFICATE_SUBMITTED, company_id)
            await self._unit_of_work.commit()
            return existing
        if not self._reader.active:
            logger.warning(
                "No certificate reader (GREEN_ENABLED or OPENAI_API_KEY unset): submission %s of company %s "
                "stays undecided",
                submission_id,
                company_id,
            )
            await self._inbox.record(event_id, CERTIFICATE_SUBMITTED, company_id)
            await self._unit_of_work.commit()
            return None

        extraction, unreadable_reason = await self._read(document)
        standing = await self._registries.company_standing(mype.ruc)
        criteria = self._policy.evaluate(
            extraction, mype.ruc, standing, self._today(), unreadable_reason=unreadable_reason
        )
        certification = GreenCertification.decide(
            submission_id=submission_id,
            mype=mype,
            document=document,
            submitted_at=submitted_at,
            extraction=extraction,
            criteria=criteria,
            reader=self._reader.name,
            source_event_id=event_id,
            now=self._clock(),
        )
        events = certification.pull_events()
        saved = await self._repository.save(certification)
        await self._publisher.publish_decided(saved)
        await self._inbox.record(event_id, CERTIFICATE_SUBMITTED, company_id)
        await self._unit_of_work.commit()
        await self._event_bus.publish(events)
        logger.info(
            "Certificate %s of company %s is %s: %s",
            saved.certification_id.value,
            company_id,
            saved.decision,
            ", ".join(f"{result.code}={'ok' if result.passed else 'no'}" for result in saved.criteria),
        )
        return saved

    async def _read(self, document: CertificateDocument) -> tuple[CertificateExtraction | None, str | None]:
        try:
            content = await self._documents.fetch(document)
        except DocumentRejectedError as error:
            return None, str(error)
        try:
            return await self._reader.read(document, content), None
        except CertificateUnreadableError as error:
            logger.warning("Could not read certificate %s: %s", document.object_key, error)
            return None, "No se pudo leer el certificado"

    @staticmethod
    def _document_type(content_type: str) -> DocumentType:
        try:
            return DocumentType(content_type.strip().lower())
        except ValueError:
            raise DomainError(f"'{content_type}' is not a certificate type: use PDF, JPEG or PNG") from None


@dataclass(frozen=True, slots=True)
class GreenStatus:
    """Whether a MYPE is green on a given day, and the certificate that says so.

    Attributes:
        code (GreenStatusCode): ``GREEN``, or why it is not.
        certification (GreenCertification | None): Its latest decided
            certificate; ``None`` if it never uploaded one.
    """

    code: GreenStatusCode
    certification: GreenCertification | None


class GreenCertificationQueryService:
    """Answers whether a MYPE is green."""

    def __init__(self, repository: GreenCertificationRepository, registries: ExternalRegistriesService) -> None:
        """Initialize the service.

        Args:
            repository (GreenCertificationRepository): Access to decisions.
            registries (ExternalRegistriesService): OEFA's register, checked again each day.
        """
        self._repository = repository
        self._registries = registries

    async def get_green_status(self, user_id: str, today: date) -> GreenStatus:
        """Tell whether a MYPE is green today, from its latest decided certificate.

        The latest one counts even if an older one was green: a MYPE that
        uploads a certificate that fails is not green, as its profile shows.

        Args:
            user_id (str): The MYPE's IAM account, the ``mypeId`` of its auctions.
            today (date): The day being asked about, in Lima.

        Returns:
            GreenStatus: The answer and the certificate behind it.
        """
        certification = await self._repository.find_latest_by_user_id(user_id)
        if certification is None:
            return GreenStatus(GreenStatusCode.NO_CERTIFICATE, None)
        standing = await self._registries.company_standing(certification.mype.ruc)
        return GreenStatus(certification.status_on(today, standing.environmental_infractions), certification)
