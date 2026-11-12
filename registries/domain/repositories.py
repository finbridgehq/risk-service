"""Repository ports of the Registries bounded context."""
from abc import ABC, abstractmethod

from registries.domain.entities import RegistrySnapshot
from registries.domain.value_objects import (
    AgentType,
    CoactiveDebtorRecord,
    EnvironmentalOffenderRecord,
    OeceSanctionRecord,
    RegistrySource,
    ShellCompanyRecord,
    TaxpayerRecord,
)


class TaxpayerRepository(ABC):
    """Read access to the local copy of the padrón reducido del RUC."""

    @abstractmethod
    async def find_by_ruc(self, ruc: str) -> TaxpayerRecord | None:
        """Return what the padrón says about a RUC, or ``None`` if it is not in it."""


class WithholdingAgentRepository(ABC):
    """Read access to the local copy of the registry of IGV agents."""

    @abstractmethod
    async def find_types_by_ruc(self, ruc: str) -> list[AgentType]:
        """Return the agent roles SUNAT gave a RUC; empty if it has none."""


class SanctionListRepository(ABC):
    """Read access to the local copy of the sanction lists, by RUC."""

    @abstractmethod
    async def find_shell_company(self, ruc: str) -> ShellCompanyRecord | None:
        """Return the RUC's entry in SUNAT's SSCO list, or ``None``."""

    @abstractmethod
    async def find_coactive_debtor(self, ruc: str) -> CoactiveDebtorRecord | None:
        """Return the RUC's entry in SUNAT's coactive-debt list, or ``None``."""

    @abstractmethod
    async def find_oece_disqualifications(self, ruc: str) -> list[OeceSanctionRecord]:
        """Return every OECE disqualification of the RUC, in force or not."""

    @abstractmethod
    async def find_oece_fines(self, ruc: str) -> list[OeceSanctionRecord]:
        """Return every unpaid OECE fine of the RUC."""

    @abstractmethod
    async def find_environmental_offender(self, ruc: str) -> EnvironmentalOffenderRecord | None:
        """Return the RUC's entry in OEFA's register of offenders, or ``None``."""


class RegistrySnapshotRepository(ABC):
    """The loads made of each registry."""

    @abstractmethod
    async def save(self, snapshot: RegistrySnapshot) -> RegistrySnapshot:
        """Insert a snapshot.

        Returns:
            RegistrySnapshot: The snapshot as stored, with its ``id`` assigned.
        """

    @abstractmethod
    async def find_latest(self, source: RegistrySource) -> RegistrySnapshot | None:
        """Return the most recent snapshot of a source, or ``None`` if it was never loaded."""
