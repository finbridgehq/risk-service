"""Aggregates of the Sustainability bounded context."""
from datetime import date, datetime

from shared.domain.entities import AggregateRoot
from shared.domain.exceptions import DomainError
from sustainability.domain.events import GreenCertificationDecided
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.domain.value_objects import (
    CertificateDocument,
    CertificateExtraction,
    CertificationId,
    CriterionResult,
    GreenDecision,
    GreenStandard,
    GreenStatusCode,
    Mype,
)

ID_MAX_LENGTH = 64


class GreenCertification(AggregateRoot):
    """The decision on one certificate a MYPE uploaded, and the checks behind it.

    One per submission: uploading a new certificate makes a new one, and the
    latest decided one is what counts for the MYPE's auctions. It is decided
    once and never changes; whether the MYPE is still green on a later day is
    asked with :meth:`status_on`.

    Attributes:
        id (int | None): Identity assigned when it is first saved.
        certification_id (CertificationId): The identifier Profile and Investment store.
        submission_id (str): Profile's identifier of the upload it decides on.
        mype (Mype): Who uploaded it.
        document (CertificateDocument): The uploaded file.
        submitted_at (datetime): When the MYPE uploaded it.
        extraction (CertificateExtraction | None): What the reader found; ``None`` if unreadable.
        criteria (tuple[CriterionResult, ...]): Every check and its result.
        decision (GreenDecision): Green or not.
        decided_at (datetime): When it was decided, in UTC.
        reader (str): What read the document, e.g. the OpenAI model.
        rules_version (str): Which rules decided, e.g. ``green-v1``.
        source_event_id (str): The Profile event it came from.
    """

    def __init__(
        self,
        certification_id: CertificationId,
        submission_id: str,
        mype: Mype,
        document: CertificateDocument,
        submitted_at: datetime,
        extraction: CertificateExtraction | None,
        criteria: tuple[CriterionResult, ...],
        decision: GreenDecision,
        decided_at: datetime,
        reader: str,
        rules_version: str,
        source_event_id: str,
        *,
        id: int | None = None,
    ) -> None:
        """Initialize a decision; also the path the repository rebuilds one through.

        Raises:
            DomainError: If a reference is blank, a timestamp has no time zone,
                there are no criteria, or a green decision lacks the facts it rests on.
        """
        super().__init__()
        for moment, what in ((submitted_at, "Submission time"), (decided_at, "Decision time")):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise DomainError(f"{what} must carry a time zone")
        if not submission_id.strip() or len(submission_id.strip()) > ID_MAX_LENGTH:
            raise DomainError(f"Submission id must be 1 to {ID_MAX_LENGTH} characters")
        if not source_event_id.strip() or not reader.strip() or not rules_version.strip():
            raise DomainError("A decision must name its source event, its reader and its rules")
        if not criteria:
            raise DomainError("A decision must keep the checks it rests on")
        if decision is GreenDecision.GREEN and (
            extraction is None
            or extraction.standard is None
            or extraction.issuer is None
            or extraction.valid_until is None
            or not all(result.passed for result in criteria)
        ):
            raise DomainError("A green decision needs a passed check for every rule and the certificate's facts")
        self._id = id
        self._certification_id = certification_id
        self._submission_id = submission_id.strip()
        self._mype = mype
        self._document = document
        self._submitted_at = submitted_at
        self._extraction = extraction
        self._criteria = criteria
        self._decision = decision
        self._decided_at = decided_at
        self._reader = reader.strip()
        self._rules_version = rules_version.strip()
        self._source_event_id = source_event_id.strip()

    @classmethod
    def decide(
        cls,
        *,
        submission_id: str,
        mype: Mype,
        document: CertificateDocument,
        submitted_at: datetime,
        extraction: CertificateExtraction | None,
        criteria: tuple[CriterionResult, ...],
        reader: str,
        source_event_id: str,
        now: datetime,
    ) -> "GreenCertification":
        """Decide on a certificate from the checks the rules made.

        Returns:
            GreenCertification: The decision, with ``GreenCertificationDecided`` recorded.
        """
        decision = GreenDecision.GREEN if GreenCertificationPolicy.is_green(criteria) else GreenDecision.NOT_GREEN
        certification = cls(
            CertificationId.new(),
            submission_id,
            mype,
            document,
            submitted_at,
            extraction,
            criteria,
            decision,
            now,
            reader,
            GreenCertificationPolicy.version,
            source_event_id,
        )
        certification.record_event(
            GreenCertificationDecided(
                certification_id=certification.certification_id.value,
                company_id=mype.company_id,
                decision=decision.value,
            )
        )
        return certification

    @property
    def id(self) -> int | None:
        """Identity assigned by the first save; ``None`` before it."""
        return self._id

    @property
    def certification_id(self) -> CertificationId:
        """The identifier Profile and Investment store."""
        return self._certification_id

    @property
    def submission_id(self) -> str:
        """Profile's identifier of the upload this decides on."""
        return self._submission_id

    @property
    def mype(self) -> Mype:
        """Who uploaded the certificate."""
        return self._mype

    @property
    def document(self) -> CertificateDocument:
        """The uploaded file."""
        return self._document

    @property
    def submitted_at(self) -> datetime:
        """When the MYPE uploaded it."""
        return self._submitted_at

    @property
    def extraction(self) -> CertificateExtraction | None:
        """What the reader found; ``None`` if the document was unreadable."""
        return self._extraction

    @property
    def criteria(self) -> tuple[CriterionResult, ...]:
        """Every check and its result."""
        return self._criteria

    @property
    def decision(self) -> GreenDecision:
        """Green or not."""
        return self._decision

    @property
    def green(self) -> bool:
        """Whether the certificate made the MYPE green when it was decided."""
        return self._decision is GreenDecision.GREEN

    @property
    def decided_at(self) -> datetime:
        """When it was decided."""
        return self._decided_at

    @property
    def reader(self) -> str:
        """What read the document."""
        return self._reader

    @property
    def rules_version(self) -> str:
        """Which rules decided."""
        return self._rules_version

    @property
    def source_event_id(self) -> str:
        """The Profile event it came from."""
        return self._source_event_id

    @property
    def standard(self) -> GreenStandard | None:
        """The accepted standard it certifies, if the reader found one."""
        return self._extraction.standard if self._extraction else None

    @property
    def issuer(self) -> str | None:
        """The certification body, if the reader found it."""
        return self._extraction.issuer if self._extraction else None

    @property
    def valid_until(self) -> date | None:
        """When the certificate expires, if the reader found it."""
        return self._extraction.valid_until if self._extraction else None

    def status_on(self, today: date, environmental_infractions: int) -> GreenStatusCode:
        """Tell whether the MYPE is still green on a later day.

        The certificate must have been green, must still be in force, and the
        MYPE must not have entered OEFA's register since.

        Args:
            today (date): The day being asked about, in Lima.
            environmental_infractions (int): Its offences in OEFA's register today.

        Returns:
            GreenStatusCode: ``GREEN``, or why it is not.
        """
        if not self.green:
            return GreenStatusCode.NOT_GREEN
        if self.valid_until is None or self.valid_until < today:
            return GreenStatusCode.EXPIRED
        if environmental_infractions > 0:
            return GreenStatusCode.ENVIRONMENTAL_OFFENDER
        return GreenStatusCode.GREEN
