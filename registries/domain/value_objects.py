"""Value objects of the Registries bounded context."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from shared.domain.exceptions import DomainError


class RegistrySource(StrEnum):
    """A public registry this service keeps a copy of."""

    TAXPAYERS = "sunat-padron-reducido"
    WITHHOLDING_AGENTS = "sunat-agentes-igv"
    SHELL_COMPANIES = "sunat-ssco"
    COACTIVE_DEBTORS = "sunat-deuda-coactiva"
    OECE_DISQUALIFICATIONS = "oece-inhabilitados"
    OECE_FINES = "oece-multas"
    ENVIRONMENTAL_OFFENDERS = "oefa-ruias"


SANCTION_SOURCES = (
    RegistrySource.SHELL_COMPANIES,
    RegistrySource.COACTIVE_DEBTORS,
    RegistrySource.OECE_DISQUALIFICATIONS,
    RegistrySource.OECE_FINES,
    RegistrySource.ENVIRONMENTAL_OFFENDERS,
)


def require_ruc(ruc: str) -> None:
    """Reject anything that is not eleven digits.

    Raises:
        DomainError: If the value is not exactly eleven digits.
    """
    if len(ruc) != 11 or not ruc.isdigit():
        raise DomainError(f"'{ruc}' is not a RUC")


class AgentType(StrEnum):
    """The roles SUNAT gives a taxpayer in collecting IGV for it.

    SUNAT designates large, reliable taxpayers as agents, so being one is a
    strong sign of a payer that pays.
    """

    WITHHOLDING = "WITHHOLDING"
    PERCEPTION_DOMESTIC_SALES = "PERCEPTION_DOMESTIC_SALES"
    PERCEPTION_FUEL = "PERCEPTION_FUEL"


@dataclass(frozen=True, slots=True)
class TaxpayerRecord:
    """One row of the padrón reducido del RUC, as this service keeps it.

    Attributes:
        ruc (str): Eleven digits.
        name (str): Name or company name as SUNAT registers it.
        status (str): Taxpayer status (``ACTIVO``, ``BAJA DE OFICIO``…), cut
            by SUNAT to 20 characters.
        domicile_condition (str): Fiscal address condition (``HABIDO``,
            ``NO HABIDO``, ``NO HALLADO…``), cut by SUNAT to 20 characters.
        ubigeo (str | None): The district's six-digit code, if SUNAT gives one.
    """

    ruc: str
    name: str
    status: str
    domicile_condition: str
    ubigeo: str | None

    def __post_init__(self) -> None:
        """Reject a RUC that is not eleven digits.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        if len(self.ruc) != 11 or not self.ruc.isdigit():
            raise DomainError(f"'{self.ruc}' is not a RUC")


@dataclass(frozen=True, slots=True)
class AgentRecord:
    """One row of the registry of IGV withholding and perception agents.

    Attributes:
        ruc (str): Eleven digits.
        agent_type (AgentType): Which role SUNAT gave it.
        since (date | None): When the role started.
        resolution (str | None): The SUNAT resolution that designated it.
    """

    ruc: str
    agent_type: AgentType
    since: date | None
    resolution: str | None

    def __post_init__(self) -> None:
        """Reject a RUC that is not eleven digits.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        if len(self.ruc) != 11 or not self.ruc.isdigit():
            raise DomainError(f"'{self.ruc}' is not a RUC")


@dataclass(frozen=True, slots=True)
class ShellCompanyRecord:
    """A taxpayer SUNAT declared without operating capacity (SSCO), by a final resolution.

    Its invoices do not back real operations: the buyer gets no tax credit
    from them. Being on the list is, for this service, a sign of a shell company.

    Attributes:
        ruc (str): Eleven digits.
        name (str): Its registered name.
        resolution (str | None): The attribution resolution.
        resolution_date (date | None): When the resolution was issued.
        final_date (date | None): When it became final.
        published_on (date | None): The list's cut-off it was published in.
    """

    ruc: str
    name: str
    resolution: str | None
    resolution_date: date | None
    final_date: date | None
    published_on: date | None

    def __post_init__(self) -> None:
        """Reject a malformed RUC.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        require_ruc(self.ruc)


@dataclass(frozen=True, slots=True)
class CoactiveDebtorRecord:
    """A large or medium taxpayer with debt in SUNAT's coactive collection.

    Attributes:
        ruc (str): Eleven digits.
        name (str): Its registered name.
        debt_amount (Decimal | None): The debt in soles, as SUNAT publishes it.
    """

    ruc: str
    name: str
    debt_amount: Decimal | None

    def __post_init__(self) -> None:
        """Reject a malformed RUC.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        require_ruc(self.ruc)


@dataclass(frozen=True, slots=True)
class OeceSanctionRecord:
    """A sanction of the public procurement authority (OECE, formerly OSCE).

    The published lists keep sanctions that already ended: whether one is in
    force is decided from its dates.

    Attributes:
        ruc (str): Eleven digits.
        resolution (str): The resolution that imposed it.
        starts_on (date | None): When it starts.
        ends_on (date | None): When it ends; ``None`` for an open-ended one.
        reason (str | None): The offence, in OECE's words.
        amount (Decimal | None): The fine in soles; ``None`` for a disqualification.
    """

    ruc: str
    resolution: str
    starts_on: date | None
    ends_on: date | None
    reason: str | None
    amount: Decimal | None

    def __post_init__(self) -> None:
        """Reject a malformed RUC.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        require_ruc(self.ruc)


@dataclass(frozen=True, slots=True)
class EnvironmentalOffenderRecord:
    """A company in the OEFA register of sanctioned environmental offenders (RUIAS).

    Entries stay on the register for five years.

    Attributes:
        ruc (str): Eleven digits.
        name (str): Its registered name.
        subsector (str | None): The economic subsector, e.g. ``Minería``.
        infractions (int): How many sanctioned offences it has.
        fine_uit (Decimal | None): The fines, in UIT, as OEFA publishes them.
    """

    ruc: str
    name: str
    subsector: str | None
    infractions: int
    fine_uit: Decimal | None

    def __post_init__(self) -> None:
        """Reject a malformed RUC.

        Raises:
            DomainError: If the RUC is not exactly eleven digits.
        """
        require_ruc(self.ruc)
