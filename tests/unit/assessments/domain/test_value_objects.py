"""Value objects refuse to exist in a bad state."""
from datetime import date
from decimal import Decimal

import pytest

from assessments.domain.value_objects import (
    AssessmentId,
    AuctionFacts,
    AuctionId,
    Currency,
    GradingDecision,
    Money,
    Payer,
    RiskGrade,
    Ruc,
)
from shared.domain.exceptions import DomainError


@pytest.mark.parametrize("value", ["2012345678", "201234567890", "2012345678a", "", "20 12345678"])
def test_ruc_must_be_eleven_digits(value: str) -> None:
    with pytest.raises(DomainError):
        Ruc(value)


def test_ruc_is_trimmed() -> None:
    assert Ruc(" 20123456789 ").value == "20123456789"


def test_new_assessment_ids_are_prefixed_and_unique() -> None:
    first, second = AssessmentId.new(), AssessmentId.new()
    assert first.value.startswith("risk-")
    assert first != second
    assert len(first.value) <= 100


@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_assessment_id_rejects_blank_or_overlong(value: str) -> None:
    with pytest.raises(DomainError):
        AssessmentId(value)


@pytest.mark.parametrize("value", ["", "x" * 65])
def test_auction_id_rejects_blank_or_overlong(value: str) -> None:
    with pytest.raises(DomainError):
        AuctionId(value)


def test_money_keeps_two_decimals_and_rejects_negatives() -> None:
    assert Money(Decimal("10.5"), Currency.PEN).amount == Decimal("10.50")
    with pytest.raises(DomainError):
        Money(Decimal("-0.01"), Currency.USD)


def test_payer_name_must_not_be_blank() -> None:
    with pytest.raises(DomainError):
        Payer(Ruc("20123456789"), "  ")


def test_auction_facts_require_invoice_and_mype() -> None:
    with pytest.raises(DomainError):
        AuctionFacts(
            auction_id=AuctionId("a-1"),
            invoice_id=" ",
            mype_id="m-1",
            payer=Payer(Ruc("20123456789"), "Pagador S.A."),
            due_date=date(2026, 12, 31),
            invoice_amount=Money(Decimal("1"), Currency.PEN),
            green_certified=False,
        )


def test_grading_decision_names_its_policy() -> None:
    with pytest.raises(DomainError):
        GradingDecision(
            eligible=True, grade=RiskGrade.A, score=80, factors=(), full_balance_outstanding=True, policy_version=" "
        )


def test_a_decision_is_either_graded_or_rejected() -> None:
    with pytest.raises(DomainError):
        GradingDecision(
            eligible=True, grade=None, score=None, factors=(), full_balance_outstanding=True, policy_version="v"
        )
    with pytest.raises(DomainError):
        GradingDecision(
            eligible=False, grade=None, score=None, factors=(), full_balance_outstanding=True, policy_version="v"
        )
    rejected = GradingDecision(
        eligible=False,
        grade=None,
        score=None,
        factors=(),
        full_balance_outstanding=True,
        policy_version="v",
        rejection_code="PAYER_NOT_ACTIVE",
        rejection_reason="Baja de oficio",
    )
    assert rejected.grade is None
