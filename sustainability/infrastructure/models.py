"""ORM models of the Sustainability bounded context."""
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.infrastructure.models import AuditableModel, Base


class GreenCertificationModel(AuditableModel, Base):
    """The ``green_certifications`` table: one row per decided upload.

    ``company_id`` and ``mype_user_id`` are plain columns, not foreign keys:
    companies belong to Profile and accounts to IAM.
    """

    __tablename__ = "green_certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    certification_id: Mapped[str] = mapped_column(String(64), unique=True)
    submission_id: Mapped[str] = mapped_column(String(64), unique=True)
    company_id: Mapped[str] = mapped_column(String(64))
    mype_user_id: Mapped[str] = mapped_column(String(64), index=True)
    ruc: Mapped[str] = mapped_column(String(11))
    business_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(40))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(String(20))
    standard: Mapped[str | None] = mapped_column(String(20))
    issuer: Mapped[str | None] = mapped_column(String(300))
    valid_until: Mapped[date | None] = mapped_column(Date)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reader: Mapped[str] = mapped_column(String(80))
    rules_version: Mapped[str] = mapped_column(String(20))
    source_event_id: Mapped[str] = mapped_column(String(64))
