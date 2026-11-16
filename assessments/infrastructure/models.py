"""ORM models of the Assessments bounded context.

These classes describe tables, nothing else. Only the repository in this
package imports them; the domain and application layers never see them.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.infrastructure.models import AuditableModel, Base


class RiskAssessmentModel(AuditableModel, Base):
    """The ``risk_assessments`` table: one row per assessed auction.

    ``auction_id``, ``invoice_id`` and ``mype_id`` are plain columns, not
    foreign keys: auctions, invoices and MYPEs belong to other services.
    """

    __tablename__ = "risk_assessments"
    __table_args__ = (Index("ix_risk_assessments_delivery_due", "delivery_status", "next_delivery_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(100), unique=True)
    auction_id: Mapped[str] = mapped_column(String(64), unique=True)
    invoice_id: Mapped[str] = mapped_column(String(64))
    mype_id: Mapped[str] = mapped_column(String(64))
    payer_ruc: Mapped[str] = mapped_column(String(11), index=True)
    payer_name: Mapped[str] = mapped_column(String(255))
    due_date: Mapped[date] = mapped_column(Date)
    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    invoice_currency: Mapped[str] = mapped_column(String(3))
    green_certified: Mapped[bool] = mapped_column(Boolean)
    green_status: Mapped[str | None] = mapped_column(String(30))
    green_certificate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    eligible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    risk_grade: Mapped[str | None] = mapped_column(String(1))
    score: Mapped[int | None] = mapped_column(Integer)
    score_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    rejection_code: Mapped[str | None] = mapped_column(String(60))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    full_balance_outstanding: Mapped[bool] = mapped_column(Boolean)
    grading_policy: Mapped[str] = mapped_column(String(40))
    provisional: Mapped[bool] = mapped_column(Boolean)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_event_id: Mapped[str] = mapped_column(String(64))
    delivery_status: Mapped[str] = mapped_column(String(20))
    delivery_attempts: Mapped[int] = mapped_column(Integer)
    next_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_error: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    investment_auction_status: Mapped[str | None] = mapped_column(String(40))


class NewsScreeningModel(Base):
    """The ``news_screenings`` table: the latest web search for negative news, one row per payer."""

    __tablename__ = "news_screenings"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(String(80))
    sources_consulted: Mapped[int] = mapped_column(Integer)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
