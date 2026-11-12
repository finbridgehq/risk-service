"""Value objects of the Sustainability bounded context.

A certificate goes through three steps, and each one has its own type: the
document the MYPE uploaded (:class:`CertificateDocument`), what the reader
found in it (:class:`CertificateExtraction`) and what the rules made of that
(:class:`CriterionResult`). Each refuses to exist in a bad state.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from shared.domain.exceptions import DomainError

CERTIFICATION_ID_PREFIX = "green-"
ID_MAX_LENGTH = 64
NAME_MAX_LENGTH = 255
TEXT_MAX_LENGTH = 300
# companies/{companyId}/sustainability/{uuid}.{ext}: what Profile signs an upload URL for.
OBJECT_KEY_PATTERN = re.compile(
    r"^companies/[0-9a-fA-F-]{36}/sustainability/[0-9a-fA-F-]{36}\.(pdf|jpg|png)$"
)


class GreenStandard(StrEnum):
    """The standards whose certificate makes a MYPE green: environmental and energy management."""

    ISO_14001 = "ISO_14001"
    ISO_50001 = "ISO_50001"


class GreenDecision(StrEnum):
    """What the rules concluded about a certificate."""

    GREEN = "GREEN"
    NOT_GREEN = "NOT_GREEN"


class CriterionCode(StrEnum):
    """The checks of the ``green-v1`` rules, in the order they are made; see ``docs/GREEN_RULES.md``."""

    CERTIFICATE_READABLE = "CERTIFICATE_READABLE"
    ACCEPTED_STANDARD = "ACCEPTED_STANDARD"
    IN_FORCE = "IN_FORCE"
    HOLDER_MATCHES_SUNAT = "HOLDER_MATCHES_SUNAT"
    NOT_ENVIRONMENTAL_OFFENDER = "NOT_ENVIRONMENTAL_OFFENDER"


class GreenStatusCode(StrEnum):
    """Why a MYPE is or is not green on a given day, the answer Assessments asks for."""

    GREEN = "GREEN"
    NO_CERTIFICATE = "NO_CERTIFICATE"
    NOT_GREEN = "NOT_GREEN"
    EXPIRED = "EXPIRED"
    ENVIRONMENTAL_OFFENDER = "ENVIRONMENTAL_OFFENDER"


class DocumentType(StrEnum):
    """The files a certificate can be uploaded as, by their media type."""

    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"

    @property
    def extension(self) -> str:
        """The file extension Profile gives this type, e.g. ``pdf``."""
        return {DocumentType.PDF: "pdf", DocumentType.JPEG: "jpg", DocumentType.PNG: "png"}[self]


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
    return value.strip()[:max_length]


@dataclass(frozen=True, slots=True)
class CertificationId:
    """The public identifier of one certificate evaluation, the one Profile and Investment store.

    Attributes:
        value (str): ``green-`` followed by a UUID.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject a blank or overlong identifier.

        Raises:
            DomainError: If the value is blank or too long.
        """
        object.__setattr__(self, "value", _required(self.value, "Certification id", ID_MAX_LENGTH))

    @classmethod
    def new(cls) -> "CertificationId":
        """Return a fresh identifier, never used before."""
        return cls(f"{CERTIFICATION_ID_PREFIX}{uuid.uuid4()}")


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
class Mype:
    """The company that uploaded the certificate, as Profile knows it.

    Attributes:
        company_id (str): Its profile, in the Profile context.
        user_id (str): Its account in IAM; the ``mypeId`` of its auctions.
        ruc (Ruc): Its taxpayer number.
        business_name (str): The name it declared in its profile.
    """

    company_id: str
    user_id: str
    ruc: Ruc
    business_name: str

    def __post_init__(self) -> None:
        """Reject blank references and names.

        Raises:
            DomainError: If an id or the name is blank or too long.
        """
        object.__setattr__(self, "company_id", _required(self.company_id, "Company id", ID_MAX_LENGTH))
        object.__setattr__(self, "user_id", _required(self.user_id, "User id", ID_MAX_LENGTH))
        object.__setattr__(self, "business_name", _required(self.business_name, "Business name", NAME_MAX_LENGTH))


@dataclass(frozen=True, slots=True)
class CertificateDocument:
    """The file the MYPE uploaded, in Profile's storage.

    Attributes:
        object_key (str): Where it is in the bucket:
            ``companies/{companyId}/sustainability/{uuid}.{ext}``.
        document_type (DocumentType): PDF, JPEG or PNG.
    """

    object_key: str
    document_type: DocumentType

    def __post_init__(self) -> None:
        """Accept only a key under a company's sustainability folder, with the type's extension.

        Anything else could make this service download a file it was never
        meant to read.

        Raises:
            DomainError: If the key has another shape or another extension.
        """
        key = self.object_key.strip()
        match = OBJECT_KEY_PATTERN.match(key)
        if match is None:
            raise DomainError(f"'{self.object_key}' is not the key of a sustainability certificate")
        if match.group(1) != self.document_type.extension:
            raise DomainError(f"A {self.document_type.value} certificate must end in .{self.document_type.extension}")
        object.__setattr__(self, "object_key", key)

    @property
    def filename(self) -> str:
        """The file's name, the last part of its key."""
        return self.object_key.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True, kw_only=True)
class CertificateExtraction:
    """What the reader found in the document; facts only, never a decision.

    Attributes:
        is_certificate (bool): Whether the document is a certificate of a
            management-system standard at all.
        standard (GreenStandard | None): The standard it certifies, when it is
            one of the accepted ones.
        standard_text (str | None): The standard as printed, e.g. ``ISO 9001:2015``.
        issuer (str | None): The certification body that issued it.
        holder_name (str | None): The company it was issued to.
        holder_ruc (str | None): The RUC printed on it, if any.
        issued_on (date | None): When it was issued.
        valid_until (date | None): When it expires.
        scope (str | None): What activities it covers.
    """

    is_certificate: bool
    standard: GreenStandard | None = None
    standard_text: str | None = None
    issuer: str | None = None
    holder_name: str | None = None
    holder_ruc: str | None = None
    issued_on: date | None = None
    valid_until: date | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        """Trim the texts and drop the blank ones."""
        for name in ("standard_text", "issuer", "holder_name", "holder_ruc", "scope"):
            object.__setattr__(self, name, _optional(getattr(self, name), TEXT_MAX_LENGTH))


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """One check of the rules and what it found.

    Attributes:
        code (CriterionCode): Which check.
        passed (bool): Whether the certificate passed it.
        detail (str): What was found, in Spanish, for the MYPE and the investor.
    """

    code: CriterionCode
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        """Keep the detail short.

        Raises:
            DomainError: If the detail is blank.
        """
        object.__setattr__(self, "detail", _required(self.detail, "Criterion detail", 1000)[:TEXT_MAX_LENGTH])


@dataclass(frozen=True, slots=True, kw_only=True)
class CompanyStanding:
    """What the public registries say about the MYPE's RUC, as far as the green rules need.

    Attributes:
        registry_loaded (bool): Whether SUNAT's padrón was ever loaded.
        registered_name (str | None): The name SUNAT has for the RUC; ``None`` if not found.
        environmental_registry_loaded (bool): Whether OEFA's register was ever loaded.
        environmental_infractions (int): Its sanctioned offences in OEFA's register.
    """

    registry_loaded: bool
    registered_name: str | None
    environmental_registry_loaded: bool
    environmental_infractions: int = 0
