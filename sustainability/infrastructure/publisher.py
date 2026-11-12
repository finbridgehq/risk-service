"""Adapter that announces decisions to Profile through the outbox.

The ``GreenCertificationIssued`` message, version 1, is this service's
contract with Profile: ``docs/contracts/green-certifications/v1``. It is
written to the outbox in the same transaction as the decision, and the relay
sends it to ``risk.green-certifications.v1`` with the company id as key.
"""
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.application.outbox import Outbox, OutboxMessage
from sustainability.application.outbound_services import GreenCertificationPublisher
from sustainability.domain.entities import GreenCertification

GREEN_CERTIFICATIONS_TOPIC = "risk.green-certifications.v1"
GREEN_CERTIFICATION_ISSUED = "GreenCertificationIssued"
SCHEMA_VERSION = 1


class OutboxGreenCertificationPublisher(GreenCertificationPublisher):
    """Queues ``GreenCertificationIssued`` in the outbox."""

    def __init__(self, outbox: Outbox) -> None:
        """Initialize the publisher on the unit of work's outbox.

        Args:
            outbox (Outbox): Shares the decision's transaction.
        """
        self._outbox = outbox

    async def publish_decided(self, certification: GreenCertification) -> None:
        event_id = str(uuid.uuid4())
        await self._outbox.add(
            OutboxMessage(
                event_id=event_id,
                event_type=GREEN_CERTIFICATION_ISSUED,
                topic=GREEN_CERTIFICATIONS_TOPIC,
                key=certification.mype.company_id,
                payload=to_message(certification, event_id, certification.decided_at),
            )
        )


def to_message(certification: GreenCertification, event_id: str, occurred_at: datetime) -> dict[str, Any]:
    """Write a decision as the ``GreenCertificationIssued`` v1 message."""
    return {
        "eventId": event_id,
        "eventType": GREEN_CERTIFICATION_ISSUED,
        "schemaVersion": SCHEMA_VERSION,
        "occurredAt": _instant(occurred_at),
        "data": {
            "certificationId": certification.certification_id.value,
            "submissionId": certification.submission_id,
            "companyId": certification.mype.company_id,
            "mypeUserId": certification.mype.user_id,
            "decision": certification.decision.value,
            "standard": certification.standard.value if certification.standard else None,
            "issuer": certification.issuer,
            "validUntil": certification.valid_until.isoformat() if certification.valid_until else None,
            "criteria": [
                {"code": result.code.value, "passed": result.passed, "detail": result.detail}
                for result in certification.criteria
            ],
            "reasonCodes": [result.code.value for result in certification.criteria if not result.passed],
            "decidedAt": _instant(certification.decided_at),
            "rulesVersion": certification.rules_version,
        },
    }


def _instant(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
