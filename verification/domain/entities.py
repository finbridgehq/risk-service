"""Aggregates of the Verification bounded context."""
from datetime import datetime

from shared.domain.entities import AggregateRoot
from shared.domain.exceptions import DomainError
from verification.domain.events import CompanyVerificationDecided
from verification.domain.services import KycPolicy
from verification.domain.value_objects import (
    Applicant,
    CheckResult,
    Evidence,
    FieldError,
    KycAssessment,
    RucDocument,
    RucDocumentFacts,
    VerificationDecision,
    VerificationId,
)

ID_MAX_LENGTH = 64


class CompanyVerification(AggregateRoot):
    """The decision on one request of a MYPE to be verified, and the checks behind it.

    One per request: sending the profile again makes a new request in Profile,
    and so a new verification. It is decided once and never changes.

    Attributes:
        id (int | None): Identity assigned when it is first saved.
        verification_id (VerificationId): The identifier Profile stores.
        request_id (str): Profile's identifier of the request it decides on.
        applicant (Applicant): Who asked, with what it declared.
        document (RucDocument): The ficha RUC it uploaded.
        requested_at (datetime): When it sent the request.
        facts (RucDocumentFacts | None): What the ficha says; ``None`` if unreadable.
        checks (tuple[CheckResult, ...]): Every check and its result.
        field_errors (tuple[FieldError, ...]): The fields to correct, only on
            ``CORRECTION_REQUIRED``.
        evidence (tuple[Evidence, ...]): Sanctions found that do not reject.
        demo (bool): Whether the ficha carries the demonstration signature.
        decision (VerificationDecision): The recommendation for Profile.
        decided_at (datetime): When it was decided, in UTC.
        rules_version (str): Which rules decided, e.g. ``kyc-v1``.
        source_event_id (str): The Profile event it came from.
    """

    def __init__(
        self,
        verification_id: VerificationId,
        request_id: str,
        applicant: Applicant,
        document: RucDocument,
        requested_at: datetime,
        facts: RucDocumentFacts | None,
        checks: tuple[CheckResult, ...],
        field_errors: tuple[FieldError, ...],
        evidence: tuple[Evidence, ...],
        demo: bool,
        decision: VerificationDecision,
        decided_at: datetime,
        rules_version: str,
        source_event_id: str,
        *,
        id: int | None = None,
    ) -> None:
        """Initialize a decision; also the path the repository rebuilds one through.

        Raises:
            DomainError: If a reference is blank, a timestamp has no time zone,
                there are no checks, or the decision contradicts its checks.
        """
        super().__init__()
        for moment, what in ((requested_at, "Request time"), (decided_at, "Decision time")):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise DomainError(f"{what} must carry a time zone")
        if not request_id.strip() or len(request_id.strip()) > ID_MAX_LENGTH:
            raise DomainError(f"Request id must be 1 to {ID_MAX_LENGTH} characters")
        if not source_event_id.strip() or not rules_version.strip():
            raise DomainError("A decision must name its source event and its rules")
        if not checks:
            raise DomainError("A decision must keep the checks it rests on")
        if decision is VerificationDecision.VERIFIED and not all(result.passed for result in checks):
            raise DomainError("A MYPE is verified only if it passed every check")
        if (decision is VerificationDecision.CORRECTION_REQUIRED) != bool(field_errors):
            raise DomainError("A correction is asked for exactly when there are fields to correct")
        self._id = id
        self._verification_id = verification_id
        self._request_id = request_id.strip()
        self._applicant = applicant
        self._document = document
        self._requested_at = requested_at
        self._facts = facts
        self._checks = checks
        self._field_errors = field_errors
        self._evidence = evidence
        self._demo = demo
        self._decision = decision
        self._decided_at = decided_at
        self._rules_version = rules_version.strip()
        self._source_event_id = source_event_id.strip()

    @classmethod
    def decide(
        cls,
        *,
        request_id: str,
        applicant: Applicant,
        document: RucDocument,
        requested_at: datetime,
        facts: RucDocumentFacts | None,
        assessment: KycAssessment,
        source_event_id: str,
        now: datetime,
    ) -> "CompanyVerification":
        """Decide on a request from the checks the rules made.

        Returns:
            CompanyVerification: The decision, with ``CompanyVerificationDecided`` recorded.
        """
        decision = KycPolicy.decide(assessment)
        verification = cls(
            VerificationId.new(),
            request_id,
            applicant,
            document,
            requested_at,
            facts,
            assessment.checks,
            assessment.field_errors if decision is VerificationDecision.CORRECTION_REQUIRED else (),
            assessment.evidence,
            assessment.demo,
            decision,
            now,
            KycPolicy.version,
            source_event_id,
        )
        verification.record_event(
            CompanyVerificationDecided(
                verification_id=verification.verification_id.value,
                company_id=applicant.company_id,
                decision=decision.value,
            )
        )
        return verification

    @property
    def id(self) -> int | None:
        """Identity assigned by the first save; ``None`` before it."""
        return self._id

    @property
    def verification_id(self) -> VerificationId:
        """The identifier Profile stores."""
        return self._verification_id

    @property
    def request_id(self) -> str:
        """Profile's identifier of the request this decides on."""
        return self._request_id

    @property
    def applicant(self) -> Applicant:
        """Who asked to be verified."""
        return self._applicant

    @property
    def document(self) -> RucDocument:
        """The ficha RUC it uploaded."""
        return self._document

    @property
    def requested_at(self) -> datetime:
        """When it sent the request."""
        return self._requested_at

    @property
    def facts(self) -> RucDocumentFacts | None:
        """What the ficha says; ``None`` if it could not be read."""
        return self._facts

    @property
    def checks(self) -> tuple[CheckResult, ...]:
        """Every check and its result."""
        return self._checks

    @property
    def field_errors(self) -> tuple[FieldError, ...]:
        """The fields to correct; empty unless a correction is asked for."""
        return self._field_errors

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        """Sanctions found that do not reject."""
        return self._evidence

    @property
    def demo(self) -> bool:
        """Whether the ficha carries the demonstration signature, not SUNAT's."""
        return self._demo

    @property
    def decision(self) -> VerificationDecision:
        """The recommendation for Profile."""
        return self._decision

    @property
    def decided_at(self) -> datetime:
        """When it was decided."""
        return self._decided_at

    @property
    def rules_version(self) -> str:
        """Which rules decided."""
        return self._rules_version

    @property
    def source_event_id(self) -> str:
        """The Profile event it came from."""
        return self._source_event_id

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """The codes of the checks that failed, in order."""
        return tuple(result.code.value for result in self._checks if not result.passed)
