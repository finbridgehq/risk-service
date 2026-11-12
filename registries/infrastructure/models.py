"""ORM models of the Registries bounded context.

Every registry table is replaced whole on every refresh (see ``bulk.py``):
they are a copy of public files, never edited row by row, so they carry no
audit columns.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.infrastructure.models import Base


class TaxpayerModel(Base):
    """The ``taxpayers`` table: the padrón reducido del RUC, one row per RUC."""

    __tablename__ = "taxpayers"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    domicile_condition: Mapped[str] = mapped_column(String(40))
    ubigeo: Mapped[str | None] = mapped_column(String(6))


class WithholdingAgentModel(Base):
    """The ``withholding_agents`` table: one row per RUC and agent role."""

    __tablename__ = "withholding_agents"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    since: Mapped[date | None] = mapped_column(Date)
    resolution: Mapped[str | None] = mapped_column(String(120))


class RegistrySnapshotModel(Base):
    """The ``registry_snapshots`` table: one row per successful load."""

    __tablename__ = "registry_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(120))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rows_loaded: Mapped[int] = mapped_column(BigInteger)
    rows_rejected: Mapped[int] = mapped_column(BigInteger)


class ShellCompanyModel(Base):
    """The ``shell_companies`` table: SUNAT's taxpayers without operating capacity (SSCO)."""

    __tablename__ = "shell_companies"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_date: Mapped[date | None] = mapped_column(Date)
    final_date: Mapped[date | None] = mapped_column(Date)
    published_on: Mapped[date | None] = mapped_column(Date)


class CoactiveDebtorModel(Base):
    """The ``coactive_debtors`` table: SUNAT's list of the largest debts in coactive collection."""

    __tablename__ = "coactive_debtors"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    debt_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class OeceDisqualificationModel(Base):
    """The ``oece_disqualifications`` table: suppliers barred from public procurement."""

    __tablename__ = "oece_disqualifications"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    resolution: Mapped[str] = mapped_column(String(120), primary_key=True)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)


class OeceFineModel(Base):
    """The ``oece_fines`` table: unpaid fines of public procurement suppliers."""

    __tablename__ = "oece_fines"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    resolution: Mapped[str] = mapped_column(String(120), primary_key=True)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class EnvironmentalOffenderModel(Base):
    """The ``environmental_offenders`` table: OEFA's register of sanctioned offenders (RUIAS)."""

    __tablename__ = "environmental_offenders"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    subsector: Mapped[str | None] = mapped_column(String(120))
    infractions: Mapped[int] = mapped_column(Integer)
    fine_uit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
