"""The kyc-v1 rules: each check, and what each set of checks decides."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.kyc_data import APPLICANT, RUC, TODAY, facts, signed_by_sunat, standing
from verification.domain.services import KycPolicy
from verification.domain.value_objects import (
    Applicant,
    CheckCode,
    EvidenceCode,
    FieldError,
    FieldErrorCode,
    KycAssessment,
    RucDocumentInspection,
    SignatureAuthority,
    TaxpayerStanding,
    VerificationDecision,
)

policy = KycPolicy()


def assess(
    inspection: RucDocumentInspection | None = None,
    taxpayer: TaxpayerStanding | None = None,
    applicant: Applicant = APPLICANT,
) -> KycAssessment:
    return policy.evaluate(applicant, inspection or signed_by_sunat(), taxpayer or standing(), TODAY)


def failed(assessment: KycAssessment) -> dict[str, str]:
    return {result.code.value: result.detail for result in assessment.checks if not result.passed}


def test_a_signed_recent_ficha_of_an_active_taxpayer_is_verified() -> None:
    assessment = assess()

    assert [result.code for result in assessment.checks] == list(CheckCode)
    assert failed(assessment) == {}
    assert assessment.field_errors == ()
    assert assessment.demo is False
    assert KycPolicy.decide(assessment) is VerificationDecision.VERIFIED


def test_the_demonstration_signature_passes_but_says_so() -> None:
    assessment = assess(RucDocumentInspection(authority=SignatureAuthority.DEMO, facts=facts()))

    signed = next(result for result in assessment.checks if result.code is CheckCode.RUC_DOCUMENT_SIGNED)
    assert signed.passed
    assert signed.detail == "Firma de demostración de Vankoo, no de SUNAT"
    assert assessment.demo is True
    assert KycPolicy.decide(assessment) is VerificationDecision.VERIFIED


def test_an_unsigned_ficha_is_rejected_with_the_reason() -> None:
    assessment = assess(RucDocumentInspection(authority=None, signature_problem="La ficha RUC no tiene firma digital"))

    assert failed(assessment)["RUC_DOCUMENT_SIGNED"] == "La ficha RUC no tiene firma digital"
    assert KycPolicy.decide(assessment) is VerificationDecision.REJECTED


@pytest.mark.parametrize(
    ("issued_on", "passed", "detail"),
    [
        (date(2026, 9, 29), True, "se emitió el 2026-09-29"),
        (date(2026, 9, 28), False, "debe tener 30 días o menos"),
        (date(2026, 10, 30), False, "es futura"),
        (None, False, "no indica su fecha"),
    ],
)
def test_the_ficha_must_be_at_most_30_days_old(issued_on: date | None, passed: bool, detail: str) -> None:
    checks = assess(signed_by_sunat(issued_on=issued_on)).checks
    result = next(r for r in checks if r.code is CheckCode.RUC_DOCUMENT_RECENT)

    assert result.passed is passed
    assert detail in result.detail


def test_a_ficha_of_another_ruc_is_rejected() -> None:
    assessment = assess(signed_by_sunat(ruc="20100047218"))

    assert failed(assessment)["RUC_DOCUMENT_MATCHES"] == f"La ficha es del RUC 20100047218, no del {RUC}"
    assert KycPolicy.decide(assessment) is VerificationDecision.REJECTED


def test_a_ficha_of_another_name_is_rejected() -> None:
    assessment = assess(signed_by_sunat(name="CONFECCIONES DEL SUR S.A.C."))

    assert "no de «TEXTILES ANDINOS" in failed(assessment)["NAME_MATCHES"]
    assert assessment.field_errors == ()
    assert KycPolicy.decide(assessment) is VerificationDecision.REJECTED


def test_a_declared_name_that_differs_from_sunat_is_a_correction() -> None:
    assessment = assess(applicant=replace(APPLICANT, business_name="Textiles del Ande"))

    assert set(failed(assessment)) == {"NAME_MATCHES"}
    assert assessment.field_errors == (FieldError("businessName", FieldErrorCode.NAME_MISMATCH),)
    assert KycPolicy.decide(assessment) is VerificationDecision.CORRECTION_REQUIRED


def test_a_declared_name_mismatch_with_another_failure_is_a_rejection() -> None:
    assessment = assess(
        RucDocumentInspection(authority=None, signature_problem="Sin firma", facts=facts()),
        applicant=replace(APPLICANT, business_name="Textiles del Ande"),
    )

    assert KycPolicy.decide(assessment) is VerificationDecision.REJECTED


@pytest.mark.parametrize(
    ("taxpayer", "code", "detail"),
    [
        (standing(status="BAJA DE OFICIO"), "TAXPAYER_ACTIVE", "figura como BAJA DE OFICIO en el padrón de SUNAT"),
        (standing(domicile_condition="NO HABIDO"), "DOMICILE_FOUND", "figura como NO HABIDO en el padrón de SUNAT"),
        (standing(shell_company=True), "NOT_SHELL_COMPANY", "sin capacidad operativa (SSCO)"),
    ],
)
def test_the_padron_and_the_ssco_list_reject(taxpayer: TaxpayerStanding, code: str, detail: str) -> None:
    assessment = assess(taxpayer=taxpayer)

    assert set(failed(assessment)) == {code}
    assert detail in failed(assessment)[code]
    assert KycPolicy.decide(assessment) is VerificationDecision.REJECTED


def test_the_padron_wins_over_what_the_ficha_says() -> None:
    assessment = assess(signed_by_sunat(status="SUSPENSION TEMPORAL"))

    assert failed(assessment) == {}


def test_a_ruc_missing_from_the_padron_is_verified_with_a_signed_ficha() -> None:
    assessment = assess(taxpayer=standing(found=False, registered_name=None, status=None, domicile_condition=None))

    found = next(result for result in assessment.checks if result.code is CheckCode.TAXPAYER_FOUND)
    assert found.passed
    assert "el estado se tomó de la ficha RUC firmada" in found.detail
    assert failed(assessment) == {}
    assert KycPolicy.decide(assessment) is VerificationDecision.VERIFIED


def test_without_the_padron_the_status_comes_from_the_signed_ficha() -> None:
    assessment = assess(
        signed_by_sunat(status="BAJA DEFINITIVA"),
        standing(found=False, registered_name=None, status=None, domicile_condition=None),
    )

    assert failed(assessment) == {"TAXPAYER_ACTIVE": "El contribuyente figura como BAJA DEFINITIVA en la ficha RUC"}


@pytest.mark.parametrize(
    "inspection",
    [
        RucDocumentInspection(authority=None, signature_problem="Sin firma", facts=facts()),
        signed_by_sunat(ruc="20100047218"),
    ],
)
def test_a_ruc_neither_in_the_padron_nor_in_a_signed_ficha_is_a_correction(
    inspection: RucDocumentInspection,
) -> None:
    assessment = assess(inspection, standing(found=False, registered_name=None, status=None, domicile_condition=None))

    assert "no figura en el padrón de SUNAT ni en una ficha RUC firmada" in failed(assessment)["TAXPAYER_FOUND"]
    assert assessment.field_errors == (FieldError("rucNumber", FieldErrorCode.RUC_NOT_FOUND),)
    assert KycPolicy.decide(assessment) is VerificationDecision.CORRECTION_REQUIRED


def test_sanctions_that_do_not_reject_are_kept_as_evidence() -> None:
    assessment = assess(
        taxpayer=standing(coactive_debt=Decimal("1520.5"), oece_sanctions=1, environmental_infractions=2)
    )

    assert failed(assessment) == {}
    assert [item.code for item in assessment.evidence] == [
        EvidenceCode.COACTIVE_DEBT,
        EvidenceCode.OECE_SANCTION,
        EvidenceCode.ENVIRONMENTAL_OFFENDER,
    ]
    assert "S/ 1,520.50" in assessment.evidence[0].detail
    assert KycPolicy.decide(assessment) is VerificationDecision.VERIFIED


def test_a_partial_set_of_checks_never_verifies() -> None:
    assessment = assess()

    assert KycPolicy.decide(replace(assessment, checks=assessment.checks[:3])) is VerificationDecision.REJECTED
