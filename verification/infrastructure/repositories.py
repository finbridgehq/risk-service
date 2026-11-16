"""SQLAlchemy implementation of the Verification repository port."""
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from verification.domain.entities import CompanyVerification
from verification.domain.repositories import CompanyVerificationRepository
from verification.domain.value_objects import (
    Applicant,
    CheckCode,
    CheckResult,
    Evidence,
    EvidenceCode,
    FieldError,
    FieldErrorCode,
    Ruc,
    RucDocument,
    RucDocumentFacts,
    VerificationDecision,
    VerificationId,
)
from verification.infrastructure.models import CompanyVerificationModel


class SqlAlchemyCompanyVerificationRepository(CompanyVerificationRepository):
    """Stores :class:`CompanyVerification` aggregates in the ``company_verifications`` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository on the unit of work's session.

        Args:
            session (AsyncSession): The session of the current unit of work.
        """
        self._session = session

    async def save(self, company_verification: CompanyVerification) -> CompanyVerification:
        model = await self._session.merge(self._to_model(company_verification))
        await self._session.flush()
        return self._to_entity(model)

    async def find_by_request_id(self, request_id: str) -> CompanyVerification | None:
        model = await self._session.scalar(
            select(CompanyVerificationModel).where(CompanyVerificationModel.request_id == request_id)
        )
        return self._to_entity(model) if model else None

    @staticmethod
    def _to_model(verification: CompanyVerification) -> CompanyVerificationModel:
        return CompanyVerificationModel(
            id=verification.id,
            verification_id=verification.verification_id.value,
            request_id=verification.request_id,
            company_id=verification.applicant.company_id,
            user_id=verification.applicant.user_id,
            ruc=verification.applicant.ruc.value,
            business_name=verification.applicant.business_name,
            object_key=verification.document.object_key,
            requested_at=verification.requested_at,
            facts=_facts_to_json(verification.facts) if verification.facts is not None else None,
            checks=[
                {"code": result.code.value, "passed": result.passed, "detail": result.detail}
                for result in verification.checks
            ],
            field_errors=[{"field": error.field, "code": error.code.value} for error in verification.field_errors],
            evidence=[{"code": item.code.value, "detail": item.detail} for item in verification.evidence],
            demo=verification.demo,
            decision=verification.decision.value,
            decided_at=verification.decided_at,
            rules_version=verification.rules_version,
            source_event_id=verification.source_event_id,
        )

    @staticmethod
    def _to_entity(model: CompanyVerificationModel) -> CompanyVerification:
        return CompanyVerification(
            VerificationId(model.verification_id),
            model.request_id,
            Applicant(
                company_id=model.company_id,
                user_id=model.user_id,
                ruc=Ruc(model.ruc),
                business_name=model.business_name,
            ),
            RucDocument(model.object_key),
            model.requested_at,
            _facts_from_json(model.facts) if model.facts is not None else None,
            tuple(
                CheckResult(CheckCode(str(item["code"])), bool(item["passed"]), str(item["detail"]))
                for item in model.checks
            ),
            tuple(FieldError(str(item["field"]), FieldErrorCode(str(item["code"]))) for item in model.field_errors),
            tuple(Evidence(EvidenceCode(str(item["code"])), str(item["detail"])) for item in model.evidence),
            model.demo,
            VerificationDecision(model.decision),
            model.decided_at,
            model.rules_version,
            model.source_event_id,
            id=model.id,
        )


def _facts_to_json(facts: RucDocumentFacts) -> dict[str, Any]:
    return {
        "ruc": facts.ruc,
        "name": facts.name,
        "status": facts.status,
        "domicileCondition": facts.domicile_condition,
        "issuedOn": facts.issued_on.isoformat() if facts.issued_on else None,
    }


def _facts_from_json(data: dict[str, Any]) -> RucDocumentFacts:
    issued_on = data.get("issuedOn")
    return RucDocumentFacts(
        ruc=data.get("ruc"),
        name=data.get("name"),
        status=data.get("status"),
        domicile_condition=data.get("domicileCondition"),
        issued_on=date.fromisoformat(issued_on) if issued_on else None,
    )
