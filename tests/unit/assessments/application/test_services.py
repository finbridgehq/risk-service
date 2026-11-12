"""Use cases of the application service, on in-memory fakes."""
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from assessments.application.outbound_services import (
    EvaluationOutcome,
    EvaluationOutcomeKind,
    InvestmentUnavailableError,
)
from assessments.domain.events import RiskAssessmentIssued
from assessments.domain.exceptions import RiskAssessmentNotFoundError
from assessments.domain.value_objects import Currency, DeliveryStatus
from registries.interfaces.acl import PayerStandingRecord
from shared.domain.events import DomainEvent
from shared.domain.exceptions import DomainError
from tests.fakes import NOW, StubEvaluationService, auction_created, build_service

ACCEPTED = EvaluationOutcome(kind=EvaluationOutcomeKind.ACCEPTED, auction_status="DRAFT")


async def test_assess_auction_grades_the_payer_from_the_registries() -> None:
    sut = build_service()
    published: list[DomainEvent] = []

    async def collect(event: DomainEvent) -> None:
        published.append(event)

    sut.event_bus.subscribe(RiskAssessmentIssued, collect)

    assessment = await sut.service.assess_auction(**auction_created())

    assert assessment is not None
    assert assessment.id == 1
    assert assessment.assessment_id.value.startswith("risk-")
    assert assessment.decision.provisional is False
    assert assessment.eligible is True
    assert assessment.grade is not None and assessment.grade.value == "B"
    assert assessment.decision.score == 60
    assert sut.registries.asked == ["20123456789"]
    assert assessment.facts.invoice_amount.amount == Decimal("10000.00")
    assert assessment.facts.invoice_amount.currency is Currency.PEN
    assert assessment.next_delivery_at == NOW
    assert sut.unit_of_work.commits == 1
    assert "10000000-0000-4000-8000-000000000001" in sut.inbox.events
    assert [type(event) for event in published] == [RiskAssessmentIssued]


async def test_a_redelivered_event_is_skipped() -> None:
    sut = build_service()
    await sut.service.assess_auction(**auction_created())

    again = await sut.service.assess_auction(**auction_created())

    assert again is None
    assert len(sut.repository.rows) == 1
    assert sut.unit_of_work.commits == 1


async def test_a_second_event_for_the_same_auction_keeps_the_first_assessment() -> None:
    sut = build_service()
    first = await sut.service.assess_auction(**auction_created())

    second = await sut.service.assess_auction(**auction_created(event_id="another-event"))

    assert first is not None and second is not None
    assert second.assessment_id == first.assessment_id
    assert len(sut.repository.rows) == 1
    assert "another-event" in sut.inbox.events


@pytest.mark.parametrize(
    "override",
    [{"payer_ruc": "123"}, {"currency": "EUR"}, {"invoice_amount": Decimal("-1")}, {"payer_name": " "}],
)
async def test_unacceptable_facts_are_refused_before_anything_is_saved(override: dict[str, Any]) -> None:
    sut = build_service()
    with pytest.raises(DomainError):
        await sut.service.assess_auction(**auction_created(**override))
    assert sut.repository.rows == {}
    assert sut.inbox.events == {}
    assert sut.unit_of_work.commits == 0


async def test_currency_code_is_case_insensitive() -> None:
    sut = build_service()
    assessment = await sut.service.assess_auction(**auction_created(currency="usd"))
    assert assessment is not None
    assert assessment.facts.invoice_amount.currency is Currency.USD


async def test_delivery_sends_the_stored_assessment_and_records_acceptance() -> None:
    sut = build_service(StubEvaluationService(outcomes=[ACCEPTED]))
    issued = await sut.service.assess_auction(**auction_created())
    assert issued is not None

    delivered = await sut.service.deliver_assessment(issued.facts.auction_id.value)

    [call] = sut.evaluations.calls
    assert call["kind"] == "evaluation"
    assert call["assessment_id"] == issued.assessment_id.value
    assert call["risk_grade"] == "B"
    assert call["full_balance_outstanding"] is True
    assert call["assessed_at"] == NOW
    assert delivered.delivery_status is DeliveryStatus.DELIVERED
    assert delivered.investment_auction_status == "DRAFT"
    assert sut.unit_of_work.commits == 2


async def test_a_refusal_settles_the_assessment_as_rejected() -> None:
    refusal = EvaluationOutcome(
        kind=EvaluationOutcomeKind.REFUSED, message="HTTP 409: Auction can no longer be evaluated"
    )
    sut = build_service(StubEvaluationService(outcomes=[refusal]))
    issued = await sut.service.assess_auction(**auction_created())
    assert issued is not None

    rejected = await sut.service.deliver_assessment(issued.facts.auction_id.value)

    assert rejected.delivery_status is DeliveryStatus.REJECTED
    assert rejected.last_delivery_error == "HTTP 409: Auction can no longer be evaluated"
    assert await sut.service.get_assessments_due_for_delivery(10) == []


async def test_an_unreachable_investment_is_retried_later_with_the_same_assessment() -> None:
    sut = build_service(StubEvaluationService(outcomes=[InvestmentUnavailableError("ConnectError"), ACCEPTED]))
    issued = await sut.service.assess_auction(**auction_created())
    assert issued is not None
    auction_id = issued.facts.auction_id.value

    pending = await sut.service.deliver_assessment(auction_id)
    assert pending.delivery_status is DeliveryStatus.PENDING
    assert pending.last_delivery_error == "ConnectError"
    assert await sut.service.get_assessments_due_for_delivery(10) == []

    sut.clock.advance(timedelta(seconds=1))
    [due] = await sut.service.get_assessments_due_for_delivery(10)
    delivered = await sut.service.deliver_assessment(due.facts.auction_id.value)

    first, second = sut.evaluations.calls
    assert first["assessment_id"] == second["assessment_id"]
    assert first["assessed_at"] == second["assessed_at"]
    assert delivered.delivery_status is DeliveryStatus.DELIVERED
    assert delivered.delivery_attempts == 2


async def test_reading_an_unknown_auction_is_not_found() -> None:
    sut = build_service()
    with pytest.raises(RiskAssessmentNotFoundError):
        await sut.service.get_risk_assessment_by_auction_id("missing")


async def test_a_payer_that_fails_the_filter_is_rejected_in_investment() -> None:
    inactive = PayerStandingRecord(
        registry_loaded=True, found=True, name="PAGADOR S.A.C.", status="BAJA DE OFICIO", domicile_condition="HABIDO"
    )
    rejected = EvaluationOutcome(kind=EvaluationOutcomeKind.ACCEPTED, auction_status="REJECTED")
    sut = build_service(StubEvaluationService(outcomes=[rejected]), standing=inactive)
    issued = await sut.service.assess_auction(**auction_created())
    assert issued is not None
    assert issued.eligible is False
    assert issued.grade is None
    assert issued.decision.rejection_code == "PAYER_NOT_ACTIVE"

    delivered = await sut.service.deliver_assessment(issued.facts.auction_id.value)

    [call] = sut.evaluations.calls
    assert call["kind"] == "rejection"
    assert call["reason_code"] == "PAYER_NOT_ACTIVE"
    assert "BAJA DE OFICIO" in str(call["reason"])
    assert delivered.delivery_status is DeliveryStatus.DELIVERED
    assert delivered.investment_auction_status == "REJECTED"


async def test_without_the_registry_the_auction_is_still_graded() -> None:
    sut = build_service(standing=PayerStandingRecord(registry_loaded=False, found=False))
    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    assert assessment.eligible is True
    assert assessment.grade is not None and assessment.grade.value == "C"


async def test_the_credit_bureau_is_asked_about_the_payer() -> None:
    from assessments.domain.value_objects import CreditReport, SbsRating

    report = CreditReport(rating=SbsRating.DEFICIENT, source="simulated-bureau-v1", simulated=True)
    sut = build_service(credit=report)
    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    assert sut.credit_bureau.asked == ["20123456789"]
    assert assessment.decision.score == 40
    assert assessment.grade is not None and assessment.grade.value == "C"


async def test_a_shell_company_payer_is_rejected() -> None:
    shell = PayerStandingRecord(
        registry_loaded=True,
        found=True,
        name="PAGADOR S.A.C.",
        status="ACTIVO",
        domicile_condition="HABIDO",
        shell_company=True,
    )
    sut = build_service(standing=shell)
    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    assert assessment.eligible is False
    assert assessment.decision.rejection_code == "PAYER_SHELL_COMPANY"


async def test_news_is_searched_once_and_reused_for_a_week() -> None:
    from datetime import timedelta

    sut = build_service()
    await sut.service.assess_auction(**auction_created())
    await sut.service.assess_auction(**auction_created(event_id="e-2", auction_id="auction-2"))
    assert sut.news_screener.searched == [("20123456789", "PAGADOR SOCIEDAD ANONIMA CERRADA")]

    sut.clock.advance(timedelta(days=8))
    await sut.service.assess_auction(**auction_created(event_id="e-3", auction_id="auction-3"))
    assert len(sut.news_screener.searched) == 2


async def test_a_failed_news_search_does_not_stop_the_assessment() -> None:
    from assessments.application.outbound_services import NewsUnavailableError
    from tests.fakes import FakeNewsScreener

    sut = build_service(news=FakeNewsScreener(NewsUnavailableError("timeout")))
    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    assert "NEWS_UNAVAILABLE" in {f.code for f in assessment.decision.factors}
    assert sut.news_screenings.rows == {}


async def test_screening_turned_off_leaves_a_note() -> None:
    from tests.fakes import FakeNewsScreener

    sut = build_service(news=FakeNewsScreener(None))
    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    assert "NEWS_NOT_SCREENED" in {f.code for f in assessment.decision.factors}
