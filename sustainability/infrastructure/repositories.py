"""SQLAlchemy implementation of the Sustainability repository port."""
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sustainability.domain.entities import GreenCertification
from sustainability.domain.repositories import GreenCertificationRepository
from sustainability.domain.value_objects import (
    CertificateDocument,
    CertificateExtraction,
    CertificationId,
    CriterionCode,
    CriterionResult,
    DocumentType,
    GreenDecision,
    GreenStandard,
    Mype,
    Ruc,
)
from sustainability.infrastructure.models import GreenCertificationModel


class SqlAlchemyGreenCertificationRepository(GreenCertificationRepository):
    """Stores :class:`GreenCertification` aggregates in the ``green_certifications`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def save(self, green_certification: GreenCertification) -> GreenCertification:
        model = await self._session.merge(self._to_model(green_certification))
        await self._session.flush()
        return self._to_entity(model)

    async def find_by_submission_id(self, submission_id: str) -> GreenCertification | None:
        model = await self._session.scalar(
            select(GreenCertificationModel).where(GreenCertificationModel.submission_id == submission_id)
        )
        return self._to_entity(model) if model else None

    async def find_latest_by_user_id(self, user_id: str) -> GreenCertification | None:
        model = await self._session.scalar(
            select(GreenCertificationModel)
            .where(GreenCertificationModel.mype_user_id == user_id)
            .order_by(GreenCertificationModel.submitted_at.desc(), GreenCertificationModel.id.desc())
            .limit(1)
        )
        return self._to_entity(model) if model else None

    @staticmethod
    def _to_model(certification: GreenCertification) -> GreenCertificationModel:
        extraction = certification.extraction
        return GreenCertificationModel(
            id=certification.id,
            certification_id=certification.certification_id.value,
            submission_id=certification.submission_id,
            company_id=certification.mype.company_id,
            mype_user_id=certification.mype.user_id,
            ruc=certification.mype.ruc.value,
            business_name=certification.mype.business_name,
            object_key=certification.document.object_key,
            content_type=certification.document.document_type.value,
            submitted_at=certification.submitted_at,
            extraction=_extraction_to_json(extraction) if extraction is not None else None,
            criteria=[
                {"code": result.code.value, "passed": result.passed, "detail": result.detail}
                for result in certification.criteria
            ],
            decision=certification.decision.value,
            standard=certification.standard.value if certification.standard else None,
            issuer=certification.issuer,
            valid_until=certification.valid_until,
            decided_at=certification.decided_at,
            reader=certification.reader,
            rules_version=certification.rules_version,
            source_event_id=certification.source_event_id,
        )

    @staticmethod
    def _to_entity(model: GreenCertificationModel) -> GreenCertification:
        return GreenCertification(
            CertificationId(model.certification_id),
            model.submission_id,
            Mype(
                company_id=model.company_id,
                user_id=model.mype_user_id,
                ruc=Ruc(model.ruc),
                business_name=model.business_name,
            ),
            CertificateDocument(model.object_key, DocumentType(model.content_type)),
            model.submitted_at,
            _extraction_from_json(model.extraction) if model.extraction is not None else None,
            tuple(
                CriterionResult(CriterionCode(str(item["code"])), bool(item["passed"]), str(item["detail"]))
                for item in model.criteria
            ),
            GreenDecision(model.decision),
            model.decided_at,
            model.reader,
            model.rules_version,
            model.source_event_id,
            id=model.id,
        )


def _extraction_to_json(extraction: CertificateExtraction) -> dict[str, Any]:
    return {
        "isCertificate": extraction.is_certificate,
        "standard": extraction.standard.value if extraction.standard else None,
        "standardText": extraction.standard_text,
        "issuer": extraction.issuer,
        "holderName": extraction.holder_name,
        "holderRuc": extraction.holder_ruc,
        "issuedOn": extraction.issued_on.isoformat() if extraction.issued_on else None,
        "validUntil": extraction.valid_until.isoformat() if extraction.valid_until else None,
        "scope": extraction.scope,
    }


def _extraction_from_json(data: dict[str, Any]) -> CertificateExtraction:
    def day(key: str) -> date | None:
        value = data.get(key)
        return date.fromisoformat(value) if value else None

    return CertificateExtraction(
        is_certificate=bool(data["isCertificate"]),
        standard=GreenStandard(data["standard"]) if data.get("standard") else None,
        standard_text=data.get("standardText"),
        issuer=data.get("issuer"),
        holder_name=data.get("holderName"),
        holder_ruc=data.get("holderRuc"),
        issued_on=day("issuedOn"),
        valid_until=day("validUntil"),
        scope=data.get("scope"),
    )
