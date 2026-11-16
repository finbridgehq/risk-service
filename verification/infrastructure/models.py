"""ORM models of the Verification bounded context."""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.infrastructure.models import AuditableModel, Base


class CompanyVerificationModel(AuditableModel, Base):
    """The ``company_verifications`` table: one row per decided request.

    ``company_id`` and ``user_id`` are plain columns, not foreign keys:
    companies belong to Profile and accounts to IAM.
    """

    __tablename__ = "company_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    verification_id: Mapped[str] = mapped_column(String(64), unique=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    company_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    ruc: Mapped[str] = mapped_column(String(11))
    business_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    field_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    demo: Mapped[bool] = mapped_column(Boolean)
    decision: Mapped[str] = mapped_column(String(30))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rules_version: Mapped[str] = mapped_column(String(20))
    source_event_id: Mapped[str] = mapped_column(String(64))
