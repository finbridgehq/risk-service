"""REST routes of the Assessments bounded context.

Assessments are created from Kafka events, never through the API, so the API
only reads. Each route translates the request into one call on the
application service and the result into a response schema.
"""
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from assessments.interfaces.dependencies import RiskAssessmentServiceDep
from assessments.interfaces.schemas import MypeRiskAssessmentResponse, RiskAssessmentResponse
from shared.interfaces.schemas import error_responses

router = APIRouter(prefix="/api/v1/risk-assessments", tags=["Risk Assessments"])
# Apart from the internal reads so the gateway can expose this prefix, and only this one.
mype_router = APIRouter(prefix="/api/v1/mype/risk-assessments", tags=["Risk Assessments"])


@router.get("/{auction_id}", responses=error_responses(400, 404))
async def get_risk_assessment_by_auction_id(
    auction_id: str, service: RiskAssessmentServiceDep
) -> RiskAssessmentResponse:
    """Get the risk assessment of an auction, and whether Investment has received it."""
    return RiskAssessmentResponse.from_entity(await service.get_risk_assessment_by_auction_id(auction_id))


@mype_router.get("/{auction_id}", responses=error_responses(400, 401, 404))
async def get_mype_risk_assessment(
    auction_id: str,
    service: RiskAssessmentServiceDep,
    x_user_id: Annotated[str | None, Header(description="The MYPE, as the gateway sets it from the JWT.")] = None,
) -> MypeRiskAssessmentResponse:
    """Get the risk assessment of one of the calling MYPE's auctions: the grade and every reason behind it."""
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-User-Id is required")
    assessment = await service.get_mype_risk_assessment(auction_id, x_user_id.strip())
    return MypeRiskAssessmentResponse.from_entity(assessment)
