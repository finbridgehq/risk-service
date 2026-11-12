"""An auction is green when its MYPE is green on the day it is assessed."""

from datetime import date

from assessments.application.outbound_services import EvaluationOutcome, EvaluationOutcomeKind
from assessments.domain.value_objects import GreenCertificate, GreenStatus
from registries.interfaces.acl import PayerStandingRecord
from sustainability.interfaces.acl import GreenCriterionRecord, GreenStatusRecord
from tests.fakes import StubEvaluationService, auction_created, build_service

ACCEPTED = EvaluationOutcome(kind=EvaluationOutcomeKind.ACCEPTED, auction_status="DRAFT")
GREEN = GreenStatusRecord(
    status="GREEN",
    certification_id="green-1",
    standard="ISO_14001",
    issuer="SGS del Perú S.A.C.",
    valid_until=date(2028, 3, 31),
    criteria=(
        GreenCriterionRecord(code="IN_FORCE", passed=True, detail="Vigente hasta el 2028-03-31"),
        GreenCriterionRecord(code="ACCEPTED_STANDARD", passed=True, detail="Certifica ISO 14001"),
    ),
)


async def test_a_green_mype_makes_the_auction_green_and_its_certificate_reaches_investment() -> None:
    sut = build_service(StubEvaluationService([ACCEPTED]), green=GREEN)

    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    await sut.service.deliver_assessment(assessment.facts.auction_id.value)

    assert assessment.green.status is GreenStatus.GREEN
    # 18:00 UTC on 14 October is still 14 October in Lima.
    assert sut.sustainability.asked == [("40000000-0000-4000-8000-000000000001", date(2026, 10, 14))]
    [call] = sut.evaluations.calls
    certificate = call["green_certificate"]
    assert isinstance(certificate, GreenCertificate)
    assert certificate.certification_id == "green-1"
    assert [criterion.code for criterion in certificate.criteria] == ["IN_FORCE", "ACCEPTED_STANDARD"]


async def test_a_mype_that_is_not_green_says_why_and_sends_no_certificate() -> None:
    sut = build_service(StubEvaluationService([ACCEPTED]), green=GreenStatusRecord(status="EXPIRED"))

    assessment = await sut.service.assess_auction(**auction_created())
    assert assessment is not None
    await sut.service.deliver_assessment(assessment.facts.auction_id.value)

    assert assessment.green.status is GreenStatus.EXPIRED
    assert sut.evaluations.calls[0]["green_certificate"] is None


async def test_an_auction_that_is_not_eligible_is_not_checked() -> None:
    not_found = PayerStandingRecord(registry_loaded=True, found=False)
    sut = build_service(standing=not_found, green=GREEN)

    assessment = await sut.service.assess_auction(**auction_created())

    assert assessment is not None
    assert not assessment.eligible
    assert assessment.green.status is GreenStatus.NOT_CHECKED
    assert sut.sustainability.asked == []


async def test_a_green_answer_without_its_certificate_counts_as_not_green() -> None:
    sut = build_service(green=GreenStatusRecord(status="GREEN"))

    assessment = await sut.service.assess_auction(**auction_created())

    assert assessment is not None
    assert assessment.green.status is GreenStatus.NOT_GREEN
