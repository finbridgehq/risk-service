"""What other bounded contexts may ask the Registries context.

Primitives in, primitives out: the caller never sees this context's model,
so the registries can change their tables without breaking the assessments.
"""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from registries.domain.value_objects import SANCTION_SOURCES, OeceSanctionRecord, RegistrySource
from registries.infrastructure.repositories import (
    SqlAlchemyRegistrySnapshotRepository,
    SqlAlchemySanctionListRepository,
    SqlAlchemyTaxpayerRepository,
    SqlAlchemyWithholdingAgentRepository,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SanctionPeriodRecord:
    """When an OECE sanction applies, and its amount if it is a fine.

    Attributes:
        starts_on (date | None): When it starts.
        ends_on (date | None): When it ends; ``None`` if open-ended.
        amount (Decimal | None): The fine in soles; ``None`` for a disqualification.
    """

    starts_on: date | None
    ends_on: date | None
    amount: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PayerStandingRecord:
    """What the public registries say about a RUC.

    Attributes:
        registry_loaded (bool): Whether the padrón was ever loaded; if not, every
            other field is empty and says nothing about the RUC.
        found (bool): Whether the RUC is in the padrón.
        name (str | None): Its registered name.
        status (str | None): Its taxpayer status, e.g. ``ACTIVO``.
        domicile_condition (str | None): Its address condition, e.g. ``HABIDO``.
        ubigeo (str | None): Its district code.
        agent_types (tuple[str, ...]): Its IGV agent roles, e.g. ``("WITHHOLDING",)``.
        shell_company (bool): SUNAT lists it without operating capacity (SSCO).
        coactive_debt (Decimal | None): Its debt in SUNAT's coactive collection,
            if it is on that list.
        oece_disqualifications (tuple[SanctionPeriodRecord, ...]): Every OECE
            disqualification, in force or not: the dates say which.
        oece_fines (tuple[SanctionPeriodRecord, ...]): Its unpaid OECE fines.
        environmental_infractions (int): Its sanctioned offences in OEFA's register.
        unavailable_sources (tuple[str, ...]): Sanction lists never loaded, so
            their absence says nothing about the RUC.
    """

    registry_loaded: bool
    found: bool
    name: str | None = None
    status: str | None = None
    domicile_condition: str | None = None
    ubigeo: str | None = None
    agent_types: tuple[str, ...] = ()
    shell_company: bool = False
    coactive_debt: Decimal | None = None
    oece_disqualifications: tuple[SanctionPeriodRecord, ...] = ()
    oece_fines: tuple[SanctionPeriodRecord, ...] = ()
    environmental_infractions: int = 0
    unavailable_sources: tuple[str, ...] = ()


class RegistriesContextFacade:
    """What other bounded contexts may ask the Registries context."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the facade on the caller's session.

        Args:
            session (AsyncSession): The caller's session, so the answer belongs to its transaction.
        """
        self._taxpayers = SqlAlchemyTaxpayerRepository(session)
        self._agents = SqlAlchemyWithholdingAgentRepository(session)
        self._sanctions = SqlAlchemySanctionListRepository(session)
        self._snapshots = SqlAlchemyRegistrySnapshotRepository(session)

    async def payer_standing(self, ruc: str) -> PayerStandingRecord:
        """Tell what the public registries say about a RUC.

        Args:
            ruc (str): Eleven digits.

        Returns:
            PayerStandingRecord: The standing; ``registry_loaded`` is false while
            the padrón has never been loaded.
        """
        if await self._snapshots.find_latest(RegistrySource.TAXPAYERS) is None:
            return PayerStandingRecord(registry_loaded=False, found=False)
        taxpayer = await self._taxpayers.find_by_ruc(ruc)
        agent_types = tuple(agent.value for agent in await self._agents.find_types_by_ruc(ruc))
        coactive = await self._sanctions.find_coactive_debtor(ruc)
        offender = await self._sanctions.find_environmental_offender(ruc)
        unavailable = [source.value for source in SANCTION_SOURCES if await self._snapshots.find_latest(source) is None]
        standing = PayerStandingRecord(
            registry_loaded=True,
            found=False,
            agent_types=agent_types,
            shell_company=await self._sanctions.find_shell_company(ruc) is not None,
            coactive_debt=coactive.debt_amount if coactive else None,
            oece_disqualifications=_periods(await self._sanctions.find_oece_disqualifications(ruc)),
            oece_fines=_periods(await self._sanctions.find_oece_fines(ruc)),
            environmental_infractions=offender.infractions if offender else 0,
            unavailable_sources=tuple(unavailable),
        )
        if taxpayer is None:
            return standing
        return replace(
            standing,
            found=True,
            name=taxpayer.name,
            status=taxpayer.status,
            domicile_condition=taxpayer.domicile_condition,
            ubigeo=taxpayer.ubigeo,
        )

def _periods(records: list[OeceSanctionRecord]) -> tuple[SanctionPeriodRecord, ...]:
    return tuple(
        SanctionPeriodRecord(starts_on=record.starts_on, ends_on=record.ends_on, amount=record.amount)
        for record in records
    )
