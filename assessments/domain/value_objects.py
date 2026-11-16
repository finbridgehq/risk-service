"""Value objects of the Assessments bounded context.

Each one refuses to exist in a bad state: a RUC that is not eleven digits, a
negative amount or a blank auction reference fails here, as a ``DomainError``,
before any assessment is built from it.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from shared.domain.exceptions import DomainError

AUCTION_ID_MAX_LENGTH = 64
ASSESSMENT_ID_MAX_LENGTH = 100
ASSESSMENT_ID_PREFIX = "risk-"
PAYER_NAME_MAX_LENGTH = 255


class RiskGrade(StrEnum):
    """The class of risk an assessment gives an auction; A is the safest."""

    A = "A"
    B = "B"
    C = "C"


class DeliveryStatus(StrEnum):
    """Whether Investment has received the assessment.

    ``PENDING`` until Investment answers; ``DELIVERED`` once it accepted the
    grade; ``REJECTED`` when it refused it for good (the auction no longer
    accepts an evaluation, or does not exist).
    """

    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class Currency(StrEnum):
    """The currencies an invoice can be issued in."""

    PEN = "PEN"
    USD = "USD"


@dataclass(frozen=True, slots=True)
class AuctionId:
    """Reference to an auction, which lives in the Investment context.

    Attributes:
        value (str): The auction's identifier as Investment assigned it.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject a blank or overlong identifier.

        Raises:
            DomainError: If the value is blank or longer than 64 characters.
        """
        normalized = self.value.strip()
        if not normalized:
            raise DomainError("Auction id must not be blank")
        if len(normalized) > AUCTION_ID_MAX_LENGTH:
            raise DomainError(f"Auction id must be at most {AUCTION_ID_MAX_LENGTH} characters")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class AssessmentId:
    """The public identifier of one assessment, the one Investment stores.

    Attributes:
        value (str): ``risk-`` followed by a UUID, e.g. ``risk-0b6f…``.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject a blank or overlong identifier.

        Raises:
            DomainError: If the value is blank or longer than Investment accepts.
        """
        normalized = self.value.strip()
        if not normalized:
            raise DomainError("Assessment id must not be blank")
        if len(normalized) > ASSESSMENT_ID_MAX_LENGTH:
            raise DomainError(f"Assessment id must be at most {ASSESSMENT_ID_MAX_LENGTH} characters")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def new(cls) -> "AssessmentId":
        """Return a fresh identifier, never used before.

        Returns:
            AssessmentId: ``risk-`` followed by a random UUID.
        """
        return cls(f"{ASSESSMENT_ID_PREFIX}{uuid.uuid4()}")


@dataclass(frozen=True, slots=True)
class Ruc:
    """A Peruvian taxpayer number (Registro Único de Contribuyentes).

    Attributes:
        value (str): Exactly eleven digits, e.g. ``20123456789``.
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
class Money:
    """An amount in one currency.

    Attributes:
        amount (Decimal): Never negative, kept to two decimals.
        currency (Currency): PEN or USD.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        """Reject a negative amount and keep two decimals.

        Raises:
            DomainError: If the amount is negative.
        """
        if self.amount < 0:
            raise DomainError("An amount of money cannot be negative")
        object.__setattr__(self, "amount", self.amount.quantize(Decimal("0.01")))


@dataclass(frozen=True, slots=True)
class Payer:
    """The company that owes the invoice; its risk is what an assessment grades.

    Attributes:
        ruc (Ruc): The payer's taxpayer number.
        name (str): The payer's name as written on the invoice.
    """

    ruc: Ruc
    name: str

    def __post_init__(self) -> None:
        """Reject a blank or overlong name.

        Raises:
            DomainError: If the name is blank or longer than 255 characters.
        """
        normalized = self.name.strip()
        if not normalized:
            raise DomainError("Payer name must not be blank")
        if len(normalized) > PAYER_NAME_MAX_LENGTH:
            raise DomainError(f"Payer name must be at most {PAYER_NAME_MAX_LENGTH} characters")
        object.__setattr__(self, "name", normalized)


@dataclass(frozen=True, slots=True)
class AuctionFacts:
    """What Investment told us about an auction when it was created.

    The grading policy decides from these facts alone, so an assessment can
    always be explained by the facts stored with it.

    Attributes:
        auction_id (AuctionId): The auction being assessed.
        invoice_id (str): The invoice behind the auction, in the Invoicing context.
        mype_id (str): The MYPE that sells the invoice.
        payer (Payer): Who owes the invoice.
        due_date (date): When the payer must pay.
        invoice_amount (Money): The invoice's total.
        green_certified (bool): Whether Investment marked the auction as green.
    """

    auction_id: AuctionId
    invoice_id: str
    mype_id: str
    payer: Payer
    due_date: date
    invoice_amount: Money
    green_certified: bool

    def __post_init__(self) -> None:
        """Reject blank references to the invoice or the MYPE.

        Raises:
            DomainError: If the invoice or MYPE id is blank.
        """
        if not self.invoice_id.strip():
            raise DomainError("Invoice id must not be blank")
        if not self.mype_id.strip():
            raise DomainError("MYPE id must not be blank")


class SbsRating(StrEnum):
    """A debtor's rating in Peru's financial system, as credit bureaus report it (SBS scale)."""

    NORMAL = "NORMAL"
    POTENTIAL_PROBLEMS = "CPP"
    DEFICIENT = "DEFICIENTE"
    DOUBTFUL = "DUDOSO"
    LOSS = "PERDIDA"


@dataclass(frozen=True, slots=True)
class CreditReport:
    """What a credit bureau says about a payer.

    Attributes:
        rating (SbsRating): Its rating in the financial system.
        source (str): Which bureau, e.g. ``simulated-bureau-v1``.
        simulated (bool): Whether the report is made up rather than bought from
            a real bureau; every factor built from it says so.
    """

    rating: SbsRating
    source: str
    simulated: bool


@dataclass(frozen=True, slots=True)
class SanctionPeriod:
    """When an OECE sanction applies, and its amount if it is a fine.

    Attributes:
        starts_on (date | None): When it starts; ``None`` if not published.
        ends_on (date | None): When it ends; ``None`` if open-ended.
        amount (Decimal | None): The fine in soles; ``None`` for a disqualification.
    """

    starts_on: date | None
    ends_on: date | None
    amount: Decimal | None = None

    def in_force_on(self, day: date) -> bool:
        """Tell whether the sanction applies on a given day."""
        started = self.starts_on is None or self.starts_on <= day
        return started and (self.ends_on is None or self.ends_on >= day)


@dataclass(frozen=True, slots=True)
class PayerStanding:
    """What the public registries say about the payer of an invoice.

    Attributes:
        registry_loaded (bool): Whether the padrón was ever loaded. If not, the
            other fields say nothing about the payer.
        found (bool): Whether the payer's RUC is in the padrón.
        name (str | None): The payer's registered name.
        status (str | None): Its taxpayer status, e.g. ``ACTIVO`` or ``BAJA DE OFICIO``.
        domicile_condition (str | None): Its fiscal address condition, e.g. ``HABIDO``.
        ubigeo (str | None): Its district code.
        withholding_agent (bool): SUNAT designated it IGV withholding agent.
        perception_agent (bool): SUNAT designated it IGV perception agent.
        shell_company (bool): SUNAT lists it without operating capacity (SSCO).
        coactive_debt (Decimal | None): Its debt in SUNAT's coactive collection,
            if it is on SUNAT's list of the largest ones.
        oece_disqualifications (tuple[SanctionPeriod, ...]): Its OECE
            disqualifications, in force or not.
        oece_fines (tuple[SanctionPeriod, ...]): Its unpaid OECE fines.
        environmental_infractions (int): Its sanctioned offences in OEFA's register.
        unavailable_sources (tuple[str, ...]): Sanction lists never loaded.
    """

    registry_loaded: bool
    found: bool
    name: str | None = None
    status: str | None = None
    domicile_condition: str | None = None
    ubigeo: str | None = None
    withholding_agent: bool = False
    perception_agent: bool = False
    shell_company: bool = False
    coactive_debt: Decimal | None = None
    oece_disqualifications: tuple[SanctionPeriod, ...] = ()
    oece_fines: tuple[SanctionPeriod, ...] = ()
    environmental_infractions: int = 0
    unavailable_sources: tuple[str, ...] = ()


class NewsCategory(StrEnum):
    """What a piece of negative news about a payer is about."""

    FRAUD = "FRAUD"
    INSOLVENCY = "INSOLVENCY"
    NON_PAYMENT_LITIGATION = "NON_PAYMENT_LITIGATION"
    CORRUPTION = "CORRUPTION"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    OTHER = "OTHER"


class NewsSeverity(StrEnum):
    """How much a piece of news weighs: fraud, insolvency and corruption are serious."""

    SERIOUS = "SERIOUS"
    MODERATE = "MODERATE"


@dataclass(frozen=True, slots=True)
class NewsFinding:
    """One piece of negative news about a payer, with the page it came from.

    Attributes:
        category (NewsCategory): What it is about.
        severity (NewsSeverity): How much it weighs.
        headline (str): The news in one line.
        url (str): The page it was read on; always one the search actually consulted.
        published_on (date | None): When it was published, if the page says.
        summary (str): What it says about the payer, in a sentence or two.
    """

    category: NewsCategory
    severity: NewsSeverity
    headline: str
    url: str
    published_on: date | None
    summary: str

    def __post_init__(self) -> None:
        """Reject a finding without headline or a page to check it on.

        Raises:
            DomainError: If the headline is blank or the URL is not http(s).
        """
        if not self.headline.strip():
            raise DomainError("A news finding needs a headline")
        if not self.url.startswith(("http://", "https://")):
            raise DomainError(f"'{self.url}' is not a web address")


@dataclass(frozen=True, slots=True)
class NewsScreening:
    """The result of searching the web for negative news about a payer.

    Attributes:
        ruc (str): The payer searched.
        findings (tuple[NewsFinding, ...]): The negative news found; empty if none.
        screened_at (datetime): When the search ran, in UTC.
        model (str): The model that read the results, e.g. ``gpt-6-luna``.
        sources_consulted (int): How many pages the search looked at.
    """

    ruc: str
    findings: tuple[NewsFinding, ...]
    screened_at: datetime
    model: str
    sources_consulted: int


class NewsCheckStatus(StrEnum):
    """Whether the payer's news could be checked for this assessment."""

    SCREENED = "SCREENED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_SCREENED = "NOT_SCREENED"


@dataclass(frozen=True, slots=True)
class NewsCheck:
    """The news check an assessment was graded with.

    Attributes:
        status (NewsCheckStatus): Checked, failed, or turned off.
        screening (NewsScreening | None): The search, when it was checked.
    """

    status: NewsCheckStatus
    screening: NewsScreening | None = None


@dataclass(frozen=True, slots=True)
class ScoreFactor:
    """One reason behind a grade, and how much it weighed.

    Attributes:
        code (str): A stable code, e.g. ``WITHHOLDING_AGENT``.
        points (int): What it added to or took from the score.
        detail (str): The reason in words, for the people reading the assessment.
    """

    code: str
    points: int
    detail: str


@dataclass(frozen=True, slots=True)
class GradingDecision:
    """What a grading policy concluded about an auction.

    An eligible decision carries a grade; a decision that is not eligible
    carries the code and the reason of the rejection instead.

    Attributes:
        eligible (bool): Whether the invoice can be funded at all.
        grade (RiskGrade | None): The risk class, when it is eligible.
        score (int | None): The points the grade came from, when there are any.
        factors (tuple[ScoreFactor, ...]): Every reason behind the decision.
        full_balance_outstanding (bool): Whether the invoice's whole balance is
            still owed; Investment only accepts auctions where it is.
        policy_version (str): Which policy decided.
        provisional (bool): Whether the policy is a stand-in, not a real
            assessment of the payer.
        rejection_code (str | None): Why it is not eligible, as a stable code.
        rejection_reason (str | None): Why it is not eligible, in words.
    """

    eligible: bool
    grade: RiskGrade | None
    score: int | None
    factors: tuple[ScoreFactor, ...]
    full_balance_outstanding: bool
    policy_version: str
    provisional: bool = False
    rejection_code: str | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        """Keep a decision either graded or rejected, never both or neither.

        Raises:
            DomainError: If the policy is not named, an eligible decision has no
                grade, or a rejection has no code and reason.
        """
        if not self.policy_version.strip():
            raise DomainError("A grading decision must name the policy that made it")
        if self.eligible and self.grade is None:
            raise DomainError("An eligible decision must carry a grade")
        if not self.eligible and (self.grade is not None or not self.rejection_code or not self.rejection_reason):
            raise DomainError("A rejection carries a code and a reason, and no grade")


class GreenStatus(StrEnum):
    """Whether the MYPE behind an auction is green, and why not when it is not.

    ``NOT_CHECKED`` is for an auction that is not eligible: its green does not matter.
    """

    GREEN = "GREEN"
    NO_CERTIFICATE = "NO_CERTIFICATE"
    NOT_GREEN = "NOT_GREEN"
    EXPIRED = "EXPIRED"
    ENVIRONMENTAL_OFFENDER = "ENVIRONMENTAL_OFFENDER"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True, slots=True)
class GreenCriterion:
    """One check the MYPE's certificate passed, as Investment shows it to investors.

    Attributes:
        code (str): Which check, e.g. ``IN_FORCE``.
        detail (str): What was found, in Spanish.
    """

    code: str
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GreenCertificate:
    """The certificate that makes the MYPE green, as Sustainability decided it.

    Attributes:
        certification_id (str): Sustainability's identifier of the decision.
        standard (str): ``ISO_14001`` or ``ISO_50001``.
        issuer (str): The certification body.
        valid_until (date): When it expires.
        criteria (tuple[GreenCriterion, ...]): The checks it passed.
    """

    certification_id: str
    standard: str
    issuer: str
    valid_until: date
    criteria: tuple[GreenCriterion, ...]

    def __post_init__(self) -> None:
        """Reject a certificate without the facts Investment needs.

        Raises:
            DomainError: If a reference is blank or there are no criteria.
        """
        if not self.certification_id.strip() or not self.standard.strip() or not self.issuer.strip():
            raise DomainError("A green certificate names its decision, its standard and its issuer")
        if not self.criteria:
            raise DomainError("A green certificate keeps the checks it passed")


@dataclass(frozen=True, slots=True)
class GreenCheck:
    """Whether the auction is green: the MYPE's status that day, and its certificate when it is green.

    Attributes:
        status (GreenStatus): ``GREEN``, or why not.
        certificate (GreenCertificate | None): Present exactly when it is green.
    """

    status: GreenStatus
    certificate: GreenCertificate | None = None

    def __post_init__(self) -> None:
        """Keep the certificate and the green status together.

        Raises:
            DomainError: If a green check has no certificate, or another one has.
        """
        if (self.status is GreenStatus.GREEN) != (self.certificate is not None):
            raise DomainError("A green check carries a certificate, and only a green one does")

    @property
    def green(self) -> bool:
        """Whether the auction is green."""
        return self.status is GreenStatus.GREEN

    @classmethod
    def not_checked(cls) -> "GreenCheck":
        """The check of an auction that is not eligible."""
        return cls(GreenStatus.NOT_CHECKED)
