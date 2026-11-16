"""Adapter that announces decisions to Profile through the outbox.

The ``CompanyVerificationIssued`` message, version 1, is this service's
contract with Profile: ``docs/contracts/company-verifications/v1``. It is
written to the outbox in the same transaction as the decision, and the relay
sends it to ``risk.company-verifications.v1`` with the company id as key.
"""
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.application.outbox import Outbox, OutboxMessage
from verification.application.outbound_services import CompanyVerificationPublisher
from verification.domain.entities import CompanyVerification

COMPANY_VERIFICATIONS_TOPIC = "risk.company-verifications.v1"
COMPANY_VERIFICATION_ISSUED = "CompanyVerificationIssued"
SCHEMA_VERSION = 1


class OutboxCompanyVerificationPublisher(CompanyVerificationPublisher):
    """Queues ``CompanyVerificationIssued`` in the outbox."""

    def __init__(self, outbox: Outbox) -> None:
        """Initialize the publisher on the unit of work's outbox.

        Args:
            outbox (Outbox): Shares the decision's transaction.
        """
        self._outbox = outbox

    async def publish_decided(self, verification: CompanyVerification) -> None:
        event_id = str(uuid.uuid4())
        await self._outbox.add(
            OutboxMessage(
                event_id=event_id,
                event_type=COMPANY_VERIFICATION_ISSUED,
                topic=COMPANY_VERIFICATIONS_TOPIC,
                key=verification.applicant.company_id,
                payload=to_message(verification, event_id, verification.decided_at),
            )
        )


def to_message(verification: CompanyVerification, event_id: str, occurred_at: datetime) -> dict[str, Any]:
    """Write a decision as the ``CompanyVerificationIssued`` v1 message."""
    return {
        "eventId": event_id,
        "eventType": COMPANY_VERIFICATION_ISSUED,
        "schemaVersion": SCHEMA_VERSION,
        "occurredAt": _instant(occurred_at),
        "data": {
            "verificationId": verification.verification_id.value,
            "requestId": verification.request_id,
            "companyId": verification.applicant.company_id,
            "userId": verification.applicant.user_id,
            "decision": verification.decision.value,
            "checks": [
                {"code": result.code.value, "passed": result.passed, "detail": result.detail}
                for result in verification.checks
            ],
            "reasonCodes": list(verification.reason_codes),
            "fieldErrors": [{"field": error.field, "code": error.code.value} for error in verification.field_errors],
            "evidence": [{"code": item.code.value, "detail": item.detail} for item in verification.evidence],
            "demo": verification.demo,
            "decidedAt": _instant(verification.decided_at),
            "rulesVersion": verification.rules_version,
        },
    }


def _instant(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
