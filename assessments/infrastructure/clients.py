"""HTTP adapter that delivers decisions to the Investment service.

It calls ``PUT /api/v1/internal/auctions/{auctionId}/evaluation`` for a grade
and ``POST /api/v1/internal/auctions/{auctionId}/rejection`` for an invoice
that is not eligible, directly on Investment (the gateway does not route
``/internal``), and translates the
answer into what the application layer understands. A green auction's grade
travels with its certificate (``greenCertification``). The one ``AsyncClient``
of the process is created in the lifespan and shared; this class never closes it.
"""
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from assessments.application.outbound_services import (
    AuctionEvaluationService,
    EvaluationOutcome,
    EvaluationOutcomeKind,
    InvestmentUnavailableError,
)
from assessments.domain.value_objects import GreenCertificate

logger = logging.getLogger(__name__)

EVALUATION_PATH = "/api/v1/internal/auctions/{auction_id}/evaluation"
REJECTION_PATH = "/api/v1/internal/auctions/{auction_id}/rejection"
MESSAGE_MAX_LENGTH = 500
# What Investment's GreenCertificationResource accepts.
GREEN_ISSUER_MAX_LENGTH = 200
GREEN_DETAIL_MAX_LENGTH = 300

# Investment answers these when the evaluation can never succeed: the auction
# does not exist (404) or no longer accepts one, or the assessment id was used
# with another grade (409). 400 means this service sent something wrong.
FINAL_REFUSALS = {httpx.codes.BAD_REQUEST, httpx.codes.NOT_FOUND, httpx.codes.CONFLICT}


class HttpxAuctionEvaluationService(AuctionEvaluationService):
    """Delivers decisions to Investment over HTTP."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Initialize the adapter on the process-wide client.

        Args:
            client (httpx.AsyncClient): A client whose ``base_url`` is Investment's.
        """
        self._client = client

    async def submit(
        self,
        *,
        auction_id: str,
        assessment_id: str,
        risk_grade: str,
        full_balance_outstanding: bool,
        assessed_at: datetime,
        green_certificate: GreenCertificate | None = None,
    ) -> EvaluationOutcome:
        body: dict[str, object] = {
            "assessmentId": assessment_id,
            "riskGrade": risk_grade,
            "fullBalanceOutstanding": full_balance_outstanding,
            "assessedAt": format_instant(assessed_at),
        }
        if green_certificate is not None:
            body["greenCertification"] = {
                "certificationId": green_certificate.certification_id,
                "standard": green_certificate.standard,
                "issuer": green_certificate.issuer[:GREEN_ISSUER_MAX_LENGTH],
                "validUntil": green_certificate.valid_until.isoformat(),
                "criteria": [
                    {"code": criterion.code, "detail": criterion.detail[:GREEN_DETAIL_MAX_LENGTH]}
                    for criterion in green_certificate.criteria
                ],
            }
        return await self._send("PUT", EVALUATION_PATH.format(auction_id=auction_id), body, auction_id)

    async def reject(
        self,
        *,
        auction_id: str,
        assessment_id: str,
        reason_code: str,
        reason: str,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        body = {
            "assessmentId": assessment_id,
            "reasonCode": reason_code,
            "reason": reason[:MESSAGE_MAX_LENGTH],
            "assessedAt": format_instant(assessed_at),
        }
        return await self._send("POST", REJECTION_PATH.format(auction_id=auction_id), body, auction_id)

    async def _send(self, method: str, path: str, body: Mapping[str, object], auction_id: str) -> EvaluationOutcome:
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise InvestmentUnavailableError(f"{type(error).__name__}: {error}") from error

        if response.is_success:
            return EvaluationOutcome(kind=EvaluationOutcomeKind.ACCEPTED, auction_status=self._auction_status(response))
        message = f"HTTP {response.status_code}: {self._message(response)}"
        if response.status_code in FINAL_REFUSALS:
            if response.status_code == httpx.codes.BAD_REQUEST:
                logger.error("Investment found the request for auction %s malformed: %s", auction_id, message)
            return EvaluationOutcome(kind=EvaluationOutcomeKind.REFUSED, message=message)
        raise InvestmentUnavailableError(message)

    @staticmethod
    def _auction_status(response: httpx.Response) -> str | None:
        try:
            status = response.json().get("status")
        except ValueError:
            return None
        return status if isinstance(status, str) else None

    @staticmethod
    def _message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:MESSAGE_MAX_LENGTH] or response.reason_phrase
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail") or payload.get("error")
            if isinstance(detail, str):
                errors = payload.get("errors")
                return (f"{detail} {errors}" if errors else detail)[:MESSAGE_MAX_LENGTH]
        return str(payload)[:MESSAGE_MAX_LENGTH]


def format_instant(moment: datetime) -> str:
    """Write a UTC instant the way Java's ``Instant`` parses it, e.g. ``2026-10-14T18:00:00.123Z``."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
