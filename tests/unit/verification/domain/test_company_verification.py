"""The CompanyVerification aggregate: what a decision must carry, and what it records."""

from dataclasses import replace
from datetime import datetime

import pytest

from shared.domain.exceptions import DomainError
from tests.kyc_data import APPLICANT, NOW, OBJECT_KEY, REQUEST_ID, TODAY, facts, signed_by_sunat, standing
from verification.domain.entities import CompanyVerification
from verification.domain.events import CompanyVerificationDecided
from verification.domain.services import KycPolicy
from verification.domain.value_objects import (
    FieldError,
    FieldErrorCode,
    KycAssessment,
    RucDocument,
    VerificationDecision,
)


def decide(assessment: KycAssessment) -> CompanyVerification:
    return CompanyVerification.decide(
        request_id=REQUEST_ID,
        applicant=APPLICANT,
        document=RucDocument(OBJECT_KEY),
        requested_at=NOW,
        facts=facts(),
        assessment=assessment,
        source_event_id="event-1",
        now=NOW,
    )


def test_a_decision_records_the_event_for_profile() -> None:
    verification = decide(KycPolicy().evaluate(APPLICANT, signed_by_sunat(), standing(), TODAY))

    assert verification.decision is VerificationDecision.VERIFIED
    assert verification.rules_version == "kyc-v1"
    assert verification.verification_id.value.startswith("kyc-")
    assert verification.reason_codes == ()
    [event] = verification.pull_events()
    assert isinstance(event, CompanyVerificationDecided)
    assert (event.verification_id, event.company_id, event.decision) == (
        verification.verification_id.value,
        APPLICANT.company_id,
        "VERIFIED",
    )


def test_field_errors_are_kept_only_when_a_correction_is_asked_for() -> None:
    assessment = KycPolicy().evaluate(
        replace(APPLICANT, business_name="Otra Empresa"),
        replace(signed_by_sunat(), authority=None, signature_problem="Sin firma"),
        standing(),
        TODAY,
    )

    verification = decide(assessment)

    assert verification.decision is VerificationDecision.REJECTED
    assert verification.field_errors == ()
    assert verification.reason_codes == ("RUC_DOCUMENT_SIGNED", "NAME_MATCHES")


def test_a_correction_keeps_its_fields() -> None:
    assessment = KycPolicy().evaluate(
        APPLICANT, signed_by_sunat(ruc="20100047218"), standing(found=False, registered_name=None), TODAY
    )

    verification = decide(assessment)

    assert verification.decision is VerificationDecision.CORRECTION_REQUIRED
    assert verification.field_errors == (FieldError("rucNumber", FieldErrorCode.RUC_NOT_FOUND),)


def test_a_verified_decision_needs_every_check_passed() -> None:
    rejected = decide(KycPolicy().evaluate(APPLICANT, signed_by_sunat(issued_on=None), standing(), TODAY))

    with pytest.raises(DomainError, match="passed every check"):
        CompanyVerification(
            rejected.verification_id,
            REQUEST_ID,
            APPLICANT,
            rejected.document,
            NOW,
            None,
            rejected.checks,
            (),
            (),
            False,
            VerificationDecision.VERIFIED,
            NOW,
            "kyc-v1",
            "event-1",
        )


def test_timestamps_must_carry_a_time_zone() -> None:
    verified = decide(KycPolicy().evaluate(APPLICANT, signed_by_sunat(), standing(), TODAY))

    with pytest.raises(DomainError, match="time zone"):
        CompanyVerification(
            verified.verification_id,
            REQUEST_ID,
            APPLICANT,
            verified.document,
            datetime(2026, 10, 29, 12),
            None,
            verified.checks,
            (),
            (),
            False,
            VerificationDecision.VERIFIED,
            NOW,
            "kyc-v1",
            "event-1",
        )


@pytest.mark.parametrize(
    "key",
    [
        "companies/50000000-0000-4000-8000-000000000002/sustainability/60000000-0000-4000-8000-000000000002.pdf",
        "companies/50000000-0000-4000-8000-000000000002/ruc/60000000-0000-4000-8000-000000000002.png",
        "../ruc/60000000-0000-4000-8000-000000000002.pdf",
    ],
)
def test_the_document_must_be_a_pdf_in_the_company_ruc_folder(key: str) -> None:
    with pytest.raises(DomainError, match="not the key of a ficha RUC"):
        RucDocument(key)
