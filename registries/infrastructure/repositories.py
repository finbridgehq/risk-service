"""SQLAlchemy implementations of the Registries repository ports."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registries.domain.entities import RegistrySnapshot
from registries.domain.repositories import (
    RegistrySnapshotRepository,
    SanctionListRepository,
    TaxpayerRepository,
    WithholdingAgentRepository,
)
from registries.domain.value_objects import (
    AgentType,
    CoactiveDebtorRecord,
    EnvironmentalOffenderRecord,
    OeceSanctionRecord,
    RegistrySource,
    ShellCompanyRecord,
    TaxpayerRecord,
)
from registries.infrastructure.models import (
    CoactiveDebtorModel,
    EnvironmentalOffenderModel,
    OeceDisqualificationModel,
    OeceFineModel,
    RegistrySnapshotModel,
    ShellCompanyModel,
    TaxpayerModel,
    WithholdingAgentModel,
)


class SqlAlchemyTaxpayerRepository(TaxpayerRepository):
    """Reads the ``taxpayers`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def find_by_ruc(self, ruc: str) -> TaxpayerRecord | None:
        model = await self._session.get(TaxpayerModel, ruc)
        if model is None:
            return None
        return TaxpayerRecord(model.ruc, model.name, model.status, model.domicile_condition, model.ubigeo)


class SqlAlchemyWithholdingAgentRepository(WithholdingAgentRepository):
    """Reads the ``withholding_agents`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def find_types_by_ruc(self, ruc: str) -> list[AgentType]:
        rows = await self._session.scalars(
            select(WithholdingAgentModel.agent_type)
            .where(WithholdingAgentModel.ruc == ruc)
            .order_by(WithholdingAgentModel.agent_type)
        )
        return [AgentType(value) for value in rows if value in AgentType.__members__.values()]


class SqlAlchemySanctionListRepository(SanctionListRepository):
    """Reads the sanction-list tables."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def find_shell_company(self, ruc: str) -> ShellCompanyRecord | None:
        model = await self._session.get(ShellCompanyModel, ruc)
        if model is None:
            return None
        return ShellCompanyRecord(
            model.ruc, model.name, model.resolution, model.resolution_date, model.final_date, model.published_on
        )

    async def find_coactive_debtor(self, ruc: str) -> CoactiveDebtorRecord | None:
        model = await self._session.get(CoactiveDebtorModel, ruc)
        return CoactiveDebtorRecord(model.ruc, model.name, model.debt_amount) if model else None

    async def find_oece_disqualifications(self, ruc: str) -> list[OeceSanctionRecord]:
        models = await self._session.scalars(
            select(OeceDisqualificationModel).where(OeceDisqualificationModel.ruc == ruc)
        )
        return [
            OeceSanctionRecord(m.ruc, m.resolution, m.starts_on, m.ends_on, m.reason, None) for m in models
        ]

    async def find_oece_fines(self, ruc: str) -> list[OeceSanctionRecord]:
        models = await self._session.scalars(select(OeceFineModel).where(OeceFineModel.ruc == ruc))
        return [
            OeceSanctionRecord(m.ruc, m.resolution, m.starts_on, m.ends_on, m.reason, m.amount) for m in models
        ]

    async def find_environmental_offender(self, ruc: str) -> EnvironmentalOffenderRecord | None:
        model = await self._session.get(EnvironmentalOffenderModel, ruc)
        if model is None:
            return None
        return EnvironmentalOffenderRecord(model.ruc, model.name, model.subsector, model.infractions, model.fine_uit)


class SqlAlchemyRegistrySnapshotRepository(RegistrySnapshotRepository):
    """Stores snapshots in the ``registry_snapshots`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def save(self, snapshot: RegistrySnapshot) -> RegistrySnapshot:
        model = await self._session.merge(
            RegistrySnapshotModel(
                id=snapshot.id,
                source=snapshot.source.value,
                version=snapshot.version,
                loaded_at=snapshot.loaded_at,
                rows_loaded=snapshot.rows_loaded,
                rows_rejected=snapshot.rows_rejected,
            )
        )
        await self._session.flush()
        return self._to_entity(model)

    async def find_latest(self, source: RegistrySource) -> RegistrySnapshot | None:
        model = await self._session.scalar(
            select(RegistrySnapshotModel)
            .where(RegistrySnapshotModel.source == source.value)
            .order_by(RegistrySnapshotModel.loaded_at.desc(), RegistrySnapshotModel.id.desc())
            .limit(1)
        )
        return self._to_entity(model) if model else None

    @staticmethod
    def _to_entity(model: RegistrySnapshotModel) -> RegistrySnapshot:
        return RegistrySnapshot(
            RegistrySource(model.source),
            model.version,
            model.loaded_at,
            model.rows_loaded,
            model.rows_rejected,
            id=model.id,
        )
