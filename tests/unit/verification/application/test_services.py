"""The use case of Verification, on in-memory fakes."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from registries.interfaces.acl import PayerStandingRecord, SanctionPeriodRecord
from shared.domain.exceptions import DomainError
from tests.kyc_data import ACTIVE_TAXPAYER, COMPANY_ID, USER_ID
from tests.kyc_fakes import FakeInspector, FakeRucDocuments, build_kyc_service, verification_requested
from verification.application.outbound_services import DocumentRejectedError, TemporarilyUnavailableError
from verification.domain.events import CompanyVerificationDecided
from verification.domain.value_objects import VerificationDecision


async def test_a_verified_mype_waits_in_the_outbox_for_profile() -> None:
    sut = build_kyc_service()
    woken: list[CompanyVerificationDecided] = []

    async def remember(event: object) -> None:
        assert isinstance(event, CompanyVerificationDecided)
        woken.append(event)

    sut.event_bus.subscribe(CompanyVerificationDecided, remember)

    verification = await sut.service.verify_company(**verification_requested())

    assert verification is not None
    assert verification.decision is VerificationDecision.VERIFIED
    assert sut.unit_of_work.commits == 1
    [message] = sut.outbox.messages
    assert message.topic == "risk.company-verifications.v1"
    assert message.key == COMPANY_ID
    data = message.payload["data"]
    assert data["decision"] == "VERIFIED"
    assert data["userId"] == USER_ID
    assert data["reasonCodes"] == []
    assert data["demo"] is False
    assert [event.decision for event in woken] == ["VERIFIED"]


async def test_a_redelivered_event_is_applied_once() -> None:
    sut = build_kyc_service()
    await sut.service.verify_company(**verification_requested())

    again = await sut.service.verify_company(**verification_requested())

    assert again is None
    assert sut.inspector.inspections == 1
    assert len(sut.outbox.messages) == 1


async def test_another_event_about_a_request_already_decided_returns_that_decision() -> None:
    sut = build_kyc_service()
    first = await sut.service.verify_company(**verification_requested())

    second = await sut.service.verify_company(**verification_requested(event_id="another-event"))

    assert second is not None and first is not None
    assert second.verification_id == first.verification_id
    assert len(sut.outbox.messages) == 1


async def test_a_missing_file_is_decided_on_as_unsigned() -> None:
    sut = build_kyc_service(documents=FakeRucDocuments(DocumentRejectedError("No se encontró el archivo")))

    verification = await sut.service.verify_company(**verification_requested())

    assert verification is not None
    assert verification.decision is VerificationDecision.REJECTED
    assert sut.inspector.inspections == 0
    assert verification.facts is None
    assert "RUC_DOCUMENT_SIGNED" in verification.reason_codes


async def test_a_storage_that_does_not_answer_stores_nothing() -> None:
    sut = build_kyc_service(documents=FakeRucDocuments(TemporarilyUnavailableError("HTTP 503")))

    with pytest.raises(TemporarilyUnavailableError):
        await sut.service.verify_company(**verification_requested())

    assert sut.repository.rows == []
    assert sut.outbox.messages == []
    assert sut.unit_of_work.commits == 0


@pytest.mark.parametrize(
    "standing",
    [
        replace(ACTIVE_TAXPAYER, registry_loaded=False, found=False),
        replace(ACTIVE_TAXPAYER, unavailable_sources=("sunat-ssco",)),
    ],
)
async def test_nothing_is_decided_until_the_padron_and_the_ssco_list_are_loaded(
    standing: PayerStandingRecord,
) -> None:
    sut = build_kyc_service(standing=standing)

    with pytest.raises(TemporarilyUnavailableError, match="never loaded"):
        await sut.service.verify_company(**verification_requested())

    assert sut.repository.rows == []
    assert sut.documents.fetched == []


async def test_a_ruc_sunat_does_not_know_asks_for_a_correction() -> None:
    sut = build_kyc_service(
        inspector=FakeInspector(),
        standing=replace(ACTIVE_TAXPAYER, found=False, name=None, status=None, domicile_condition=None),
    )

    verification = await sut.service.verify_company(**verification_requested(ruc="20999999999"))

    assert verification is not None
    assert verification.decision is VerificationDecision.CORRECTION_REQUIRED
    assert sut.outbox.messages[0].payload["data"]["fieldErrors"] == [{"field": "rucNumber", "code": "RUC_NOT_FOUND"}]


async def test_sanctions_that_do_not_reject_travel_as_evidence() -> None:
    sut = build_kyc_service(
        standing=replace(
            ACTIVE_TAXPAYER,
            coactive_debt=Decimal("800"),
            oece_disqualifications=(
                SanctionPeriodRecord(starts_on=date(2026, 1, 1), ends_on=date(2027, 1, 1)),
                SanctionPeriodRecord(starts_on=date(2020, 1, 1), ends_on=date(2021, 1, 1)),
            ),
        )
    )

    await sut.service.verify_company(**verification_requested())

    data = sut.outbox.messages[0].payload["data"]
    assert data["decision"] == "VERIFIED"
    assert [item["code"] for item in data["evidence"]] == ["COACTIVE_DEBT", "OECE_SANCTION"]
    assert "1 sanción(es)" in data["evidence"][1]["detail"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ruc": "123"}, "not a RUC"),
        ({"object_key": f"companies/{COMPANY_ID}/sustainability/x.pdf"}, "not the key of a ficha RUC"),
        ({"business_name": " "}, "Business name"),
    ],
)
async def test_unacceptable_facts_are_refused(override: dict[str, str], message: str) -> None:
    sut = build_kyc_service()

    with pytest.raises(DomainError, match=message):
        await sut.service.verify_company(**verification_requested(**override))
