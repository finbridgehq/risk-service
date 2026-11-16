"""Response schemas of the Assessments REST API."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from assessments.domain.entities import RiskAssessment
from assessments.domain.value_objects import Currency, DeliveryStatus, GreenCertificate, GreenStatus, RiskGrade


class ScoreFactorResponse(BaseModel):
    """One reason behind a decision, and how much it weighed."""

    code: str
    points: int
    detail: str


class GreenCriterionResponse(BaseModel):
    """One check the MYPE's certificate passed."""

    code: str
    detail: str


class GreenCertificateResponse(BaseModel):
    """The certificate that makes the auction green."""

    certification_id: str
    standard: str
    issuer: str
    valid_until: date
    criteria: list[GreenCriterionResponse]

    @classmethod
    def from_value(cls, certificate: GreenCertificate | None) -> "GreenCertificateResponse | None":
        """Build the response from the value object, or ``None`` when the auction is not green."""
        if certificate is None:
            return None
        return cls(
            certification_id=certificate.certification_id,
            standard=certificate.standard,
            issuer=certificate.issuer,
            valid_until=certificate.valid_until,
            criteria=[GreenCriterionResponse(code=item.code, detail=item.detail) for item in certificate.criteria],
        )


class RiskAssessmentResponse(BaseModel):
    """A risk assessment as the API returns it.

    ``eligible`` says whether the invoice can be funded; if it can,
    ``risk_grade`` and ``score`` say how risky it is, and if it cannot,
    ``rejection_code`` and ``rejection_reason`` say why. ``factors`` lists
    every reason behind the decision. ``provisional`` is true only for the
    assessments of phase 1, graded by a stand-in that did not look at the payer.
    ``green_status`` says whether the MYPE was green that day, and
    ``green_certificate`` carries the certificate when it was; ``green_certified``
    is only what Investment published when it created the auction.
    """

    assessment_id: str
    auction_id: str
    invoice_id: str
    mype_id: str
    payer_ruc: str
    payer_name: str
    due_date: date
    invoice_amount: Decimal
    currency: Currency
    green_certified: bool
    green_status: GreenStatus
    green_certificate: GreenCertificateResponse | None
    eligible: bool
    risk_grade: RiskGrade | None
    score: int | None
    factors: list[ScoreFactorResponse]
    rejection_code: str | None
    rejection_reason: str | None
    full_balance_outstanding: bool
    grading_policy: str
    provisional: bool
    assessed_at: datetime
    delivery_status: DeliveryStatus
    delivery_attempts: int
    next_delivery_at: datetime | None
    last_delivery_error: str | None
    delivered_at: datetime | None
    investment_auction_status: str | None

    @classmethod
    def from_entity(cls, assessment: RiskAssessment) -> "RiskAssessmentResponse":
        """Build the response from the aggregate.

        Args:
            assessment (RiskAssessment): A stored assessment.

        Returns:
            RiskAssessmentResponse: Its public representation.
        """
        facts = assessment.facts
        return cls(
            assessment_id=assessment.assessment_id.value,
            auction_id=facts.auction_id.value,
            invoice_id=facts.invoice_id,
            mype_id=facts.mype_id,
            payer_ruc=facts.payer.ruc.value,
            payer_name=facts.payer.name,
            due_date=facts.due_date,
            invoice_amount=facts.invoice_amount.amount,
            currency=facts.invoice_amount.currency,
            green_certified=facts.green_certified,
            green_status=assessment.green.status,
            green_certificate=GreenCertificateResponse.from_value(assessment.green.certificate),
            eligible=assessment.eligible,
            risk_grade=assessment.grade,
            score=assessment.decision.score,
            factors=[
                ScoreFactorResponse(code=factor.code, points=factor.points, detail=factor.detail)
                for factor in assessment.decision.factors
            ],
            rejection_code=assessment.decision.rejection_code,
            rejection_reason=assessment.decision.rejection_reason,
            full_balance_outstanding=assessment.decision.full_balance_outstanding,
            grading_policy=assessment.decision.policy_version,
            provisional=assessment.decision.provisional,
            assessed_at=assessment.assessed_at,
            delivery_status=assessment.delivery_status,
            delivery_attempts=assessment.delivery_attempts,
            next_delivery_at=assessment.next_delivery_at,
            last_delivery_error=assessment.last_delivery_error,
            delivered_at=assessment.delivered_at,
            investment_auction_status=assessment.investment_auction_status,
        )


class MypeRiskAssessmentResponse(BaseModel):
    """What the MYPE may see of its own invoice's risk assessment.

    The decision and its reasons, without the delivery bookkeeping or the inputs
    Investment sent: ``factors`` lists every reason with the points it weighed,
    ``score`` and ``risk_grade`` what they added up to, and ``rejection_code`` and
    ``rejection_reason`` why it cannot be funded when ``eligible`` is false.
    """

    auction_id: str
    invoice_id: str
    payer_ruc: str
    payer_name: str
    eligible: bool
    risk_grade: RiskGrade | None
    score: int | None
    factors: list[ScoreFactorResponse]
    rejection_code: str | None
    rejection_reason: str | None
    provisional: bool
    assessed_at: datetime

    @classmethod
    def from_entity(cls, assessment: RiskAssessment) -> "MypeRiskAssessmentResponse":
        """Build the response from the aggregate.

        Args:
            assessment (RiskAssessment): A stored assessment.

        Returns:
            MypeRiskAssessmentResponse: What its MYPE may see of it.
        """
        full = RiskAssessmentResponse.from_entity(assessment)
        return cls(**full.model_dump(include=set(cls.model_fields)))
