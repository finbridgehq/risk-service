"""Value objects of the Verification bounded context.

A verification goes through three steps, and each one has its own type: the
ficha RUC the MYPE uploaded (:class:`RucDocument`), what its signature and its
text say (:class:`RucDocumentInspection`) and what the rules made of that
(:class:`CheckResult`). Each refuses to exist in a bad state.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from shared.domain.exceptions import DomainError

VERIFICATION_ID_PREFIX = "kyc-"
ID_MAX_LENGTH = 64
NAME_MAX_LENGTH = 255
TEXT_MAX_LENGTH = 300
# companies/{companyId}/ruc/{uuid}.pdf: what Profile signs an upload URL for.
OBJECT_KEY_PATTERN = re.compile(r"^companies/[0-9a-fA-F-]{36}/ruc/[0-9a-fA-F-]{36}\.pdf$")


class VerificationDecision(StrEnum):
    """What the rules concluded about a MYPE.

    ``CORRECTION_REQUIRED`` is not a rejection: the MYPE typed something that
    cannot be checked (a RUC SUNAT does not know), fixes it and sends it again
    without waiting.
    """

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


class CheckCode(StrEnum):
    """The checks of the ``kyc-v1`` rules, in the order they are made; see ``docs/KYC_RULES.md``."""

    TAXPAYER_FOUND = "TAXPAYER_FOUND"
    RUC_DOCUMENT_SIGNED = "RUC_DOCUMENT_SIGNED"
    RUC_DOCUMENT_RECENT = "RUC_DOCUMENT_RECENT"
    RUC_DOCUMENT_MATCHES = "RUC_DOCUMENT_MATCHES"
    NAME_MATCHES = "NAME_MATCHES"
    TAXPAYER_ACTIVE = "TAXPAYER_ACTIVE"
    DOMICILE_FOUND = "DOMICILE_FOUND"
    NOT_SHELL_COMPANY = "NOT_SHELL_COMPANY"


class FieldErrorCode(StrEnum):
    """Why a field the MYPE typed must be corrected."""

    RUC_NOT_FOUND = "RUC_NOT_FOUND"
    NAME_MISMATCH = "NAME_MISMATCH"


class EvidenceCode(StrEnum):
    """Sanctions found that do not reject a MYPE under ``kyc-v1``, kept for whoever reviews it."""

    COACTIVE_DEBT = "COACTIVE_DEBT"
    OECE_SANCTION = "OECE_SANCTION"
    ENVIRONMENTAL_OFFENDER = "ENVIRONMENTAL_OFFENDER"


class SignatureAuthority(StrEnum):
    """Whose signature a ficha RUC carries, when it carries a valid one.

    ``DEMO`` is a temporary patch for the demonstrations: fichas signed by a
    local certificate of Vankoo's, accepted only when ``KYC_DEMO_CA_PATH`` is
    set, and always shown as a demo. See ``docs/KYC_RULES.md``.
    """

    SUNAT = "SUNAT"
    DEMO = "DEMO"


def _required(value: str, what: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainError(f"{what} must not be blank")
    if len(normalized) > max_length:
        raise DomainError(f"{what} must be at most {max_length} characters")
    return normalized


def _optional(value: str | None, max_length: int) -> str | None:
    if value is None or not value.strip():
        return None
    return " ".join(value.split())[:max_length]


@dataclass(frozen=True, slots=True)
class VerificationId:
    """The public identifier of one verification.

    Attributes:
        value (str): ``kyc-`` followed by a UUID.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject a blank or overlong identifier.

        Raises:
            DomainError: If the value is blank or too long.
        """
        object.__setattr__(self, "value", _required(self.value, "Verification id", ID_MAX_LENGTH))

    @classmethod
    def new(cls) -> "VerificationId":
        """Return a fresh identifier, never used before."""
        return cls(f"{VERIFICATION_ID_PREFIX}{uuid.uuid4()}")


@dataclass(frozen=True, slots=True)
class Ruc:
    """A Peruvian taxpayer number.

    Attributes:
        value (str): Exactly eleven digits.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject anything that is not eleven digits.

        Raises:
            DomainError: If the value is not exactly eleven digits.
        """
        normalized = self.value.strip()
        if len(normalized) != 11 or not normalized.isdigit():
            raise DomainError(f"'{self.value}' is not a RUC: it must be exactly 11 digits")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class Applicant:
    """The MYPE asking to be verified, with the data it typed in Profile.

    Attributes:
        company_id (str): Its profile, in the Profile context.
        user_id (str): Its account in IAM.
        ruc (Ruc): The RUC it declared.
        business_name (str): The name it declared.
    """

    company_id: str
    user_id: str
    ruc: Ruc
    business_name: str

    def __post_init__(self) -> None:
        """Reject blank references and names.

        Raises:
            DomainError: If a reference or the name is blank or too long.
        """
        object.__setattr__(self, "company_id", _required(self.company_id, "Company id", ID_MAX_LENGTH))
        object.__setattr__(self, "user_id", _required(self.user_id, "User id", ID_MAX_LENGTH))
        object.__setattr__(self, "business_name", _required(self.business_name, "Business name", NAME_MAX_LENGTH))


@dataclass(frozen=True, slots=True)
class RucDocument:
    """The ficha RUC the MYPE uploaded to Profile's bucket.

    Attributes:
        object_key (str): Its key, ``companies/{companyId}/ruc/{uuid}.pdf``.
    """

    object_key: str

    def __post_init__(self) -> None:
        """Reject a key outside a company's ``ruc`` folder.

        Raises:
            DomainError: If the key is not one Profile issues for a ficha RUC.
        """
        if not OBJECT_KEY_PATTERN.fullmatch(self.object_key):
            raise DomainError(f"'{self.object_key}' is not the key of a ficha RUC")


@dataclass(frozen=True, slots=True)
class RucDocumentFacts:
    """What is printed on a ficha RUC; any of it may be missing.

    Attributes:
        ruc (str | None): The RUC it reports on.
        name (str | None): The taxpayer's name or business name.
        status (str | None): «Estado del Contribuyente», e.g. ``ACTIVO``.
        domicile_condition (str | None): «Condición del Domicilio Fiscal», e.g. ``HABIDO``.
        issued_on (date | None): The day SUNAT issued the report.
    """

    ruc: str | None = None
    name: str | None = None
    status: str | None = None
    domicile_condition: str | None = None
    issued_on: date | None = None

    def __post_init__(self) -> None:
        """Normalize the texts: single spaces, upper case for the codes, within their limits."""
        object.__setattr__(self, "ruc", _optional(self.ruc, 11))
        object.__setattr__(self, "name", _optional(self.name, NAME_MAX_LENGTH))
        for attribute in ("status", "domicile_condition"):
            value = _optional(getattr(self, attribute), 60)
            object.__setattr__(self, attribute, value.upper() if value else None)


@dataclass(frozen=True, slots=True)
class RucDocumentInspection:
    """What the inspector found in a ficha RUC: whose signature, and what it says.

    Attributes:
        authority (SignatureAuthority | None): Whose valid signature covers the
            whole file; ``None`` if it has none.
        signature_problem (str | None): Why it is not signed, when it is not.
        facts (RucDocumentFacts | None): Its text; ``None`` if it could not be read.
    """

    authority: SignatureAuthority | None
    signature_problem: str | None = None
    facts: RucDocumentFacts | None = None

    def __post_init__(self) -> None:
        """Require a reason when there is no signature.

        Raises:
            DomainError: If a ficha without a valid signature carries no reason.
        """
        if self.authority is None and not (self.signature_problem and self.signature_problem.strip()):
            raise DomainError("An unsigned ficha must say why it is not signed")

    @classmethod
    def unusable(cls, reason: str) -> "RucDocumentInspection":
        """A file that could not be inspected at all (missing, not a PDF, too large)."""
        return cls(authority=None, signature_problem=reason, facts=None)

    @property
    def signed(self) -> bool:
        """Whether a trusted signature covers the whole file."""
        return self.authority is not None

    @property
    def demo(self) -> bool:
        """Whether that signature is the demonstration one."""
        return self.authority is SignatureAuthority.DEMO


@dataclass(frozen=True, slots=True, kw_only=True)
class TaxpayerStanding:
    """What the public registries say about the declared RUC.

    Attributes:
        registry_loaded (bool): Whether the padrón was ever loaded.
        shell_registry_loaded (bool): Whether the SSCO list was ever loaded.
        found (bool): Whether the RUC is in the padrón.
        registered_name (str | None): Its name in the padrón.
        status (str | None): Its status in the padrón, e.g. ``ACTIVO``.
        domicile_condition (str | None): Its condition in the padrón, e.g. ``HABIDO``.
        shell_company (bool): SUNAT lists it without operating capacity (SSCO).
        coactive_debt (Decimal | None): Its debt in coactive collection, if listed.
        oece_sanctions (int): OECE disqualifications in force and unpaid fines.
        environmental_infractions (int): Its offences in OEFA's register.
    """

    registry_loaded: bool
    shell_registry_loaded: bool
    found: bool
    registered_name: str | None = None
    status: str | None = None
    domicile_condition: str | None = None
    shell_company: bool = False
    coactive_debt: Decimal | None = None
    oece_sanctions: int = 0
    environmental_infractions: int = 0


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check of the rules and its outcome.

    Attributes:
        code (CheckCode): Which check.
        passed (bool): Whether it passed.
        detail (str): Why, in Spanish, for the MYPE and whoever reviews it.
    """

    code: CheckCode
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        """Trim the detail and require one.

        Raises:
            DomainError: If the detail is blank.
        """
        object.__setattr__(self, "detail", _required(self.detail, "Check detail", TEXT_MAX_LENGTH))


@dataclass(frozen=True, slots=True)
class FieldError:
    """A field the MYPE must correct before sending it again.

    Attributes:
        field (str): The field, as Profile names it, e.g. ``rucNumber``.
        code (FieldErrorCode): What is wrong with it.
    """

    field: str
    code: FieldErrorCode


@dataclass(frozen=True, slots=True)
class Evidence:
    """A sanction found that does not reject the MYPE under ``kyc-v1``.

    Attributes:
        code (EvidenceCode): Which list.
        detail (str): What it says, in Spanish.
    """

    code: EvidenceCode
    detail: str

    def __post_init__(self) -> None:
        """Trim the detail and require one.

        Raises:
            DomainError: If the detail is blank.
        """
        object.__setattr__(self, "detail", _required(self.detail, "Evidence detail", TEXT_MAX_LENGTH))


@dataclass(frozen=True, slots=True)
class KycAssessment:
    """Everything the rules found, before it becomes a decision.

    Attributes:
        checks (tuple[CheckResult, ...]): Every check, in order.
        field_errors (tuple[FieldError, ...]): Fields to correct; any makes it
            ``CORRECTION_REQUIRED``.
        evidence (tuple[Evidence, ...]): Sanctions that do not reject.
        demo (bool): Whether the ficha carries the demonstration signature.
    """

    checks: tuple[CheckResult, ...]
    field_errors: tuple[FieldError, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    demo: bool = False
