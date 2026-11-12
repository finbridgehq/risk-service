"""The green-v1 rules: each check, and what makes a certificate green."""

from dataclasses import replace
from datetime import date

import pytest

from shared.domain.names import normalize_company_name
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.domain.value_objects import (
    CertificateExtraction,
    CompanyStanding,
    CriterionCode,
    GreenStandard,
    Ruc,
)
from tests.green_data import RUC, TODAY, iso_14001

STANDING = CompanyStanding(
    registry_loaded=True,
    registered_name="AGROEXPORT VERDE SOCIEDAD ANONIMA CERRADA",
    environmental_registry_loaded=True,
)
policy = GreenCertificationPolicy()


def results(
    extraction: CertificateExtraction | None = None, standing: CompanyStanding = STANDING
) -> dict[str, tuple[bool, str]]:
    checked = policy.evaluate(extraction or iso_14001(), Ruc(RUC), standing, TODAY)
    return {result.code.value: (result.passed, result.detail) for result in checked}


@pytest.mark.parametrize(
    ("printed", "registered"),
    [
        ("Agroexport Verde S.A.C.", "AGROEXPORT VERDE SOCIEDAD ANONIMA CERRADA"),
        ("AGROEXPORT VERDE SAC", "Agroexport  Verde S.A.C."),
        ("Café Montaña E.I.R.L.", "CAFE MONTAÑA EMPRESA INDIVIDUAL DE RESPONSABILIDAD LIMITADA"),
        ("Molino El Triunfo S.A.", "MOLINO EL TRIUNFO S A"),
    ],
)
def test_names_of_the_same_company_compare_equal(printed: str, registered: str) -> None:
    assert normalize_company_name(printed) == normalize_company_name(registered)


def test_a_different_company_does_not_compare_equal() -> None:
    assert normalize_company_name("Agroexport Verde Norte S.A.C.") != normalize_company_name("AGROEXPORT VERDE S.A.C.")


def test_a_name_that_is_only_a_legal_form_is_kept() -> None:
    assert normalize_company_name("S.A.") == "S A"


def test_a_valid_iso_14001_of_the_mype_passes_every_check() -> None:
    criteria = policy.evaluate(iso_14001(), Ruc(RUC), STANDING, TODAY)

    assert [r.code for r in criteria] == list(CriterionCode)
    assert all(r.passed for r in criteria)
    assert GreenCertificationPolicy.is_green(criteria)
    assert results()["IN_FORCE"] == (True, "Vigente hasta el 2028-03-31")


def test_iso_50001_is_accepted_too() -> None:
    assert results(iso_14001(standard=GreenStandard.ISO_50001, standard_text="ISO 50001:2018"))["ACCEPTED_STANDARD"][0]


def test_an_unreadable_document_stops_at_the_first_check() -> None:
    criteria = policy.evaluate(None, Ruc(RUC), STANDING, TODAY, unreadable_reason="No se pudo leer el certificado")

    assert [(r.code, r.passed, r.detail) for r in criteria] == [
        (CriterionCode.CERTIFICATE_READABLE, False, "No se pudo leer el certificado")
    ]
    assert not GreenCertificationPolicy.is_green(criteria)


def test_a_document_that_is_not_a_certificate_is_not_readable() -> None:
    criteria = policy.evaluate(iso_14001(is_certificate=False), Ruc(RUC), STANDING, TODAY)

    assert [r.code for r in criteria] == [CriterionCode.CERTIFICATE_READABLE]


def test_another_standard_fails() -> None:
    passed, detail = results(iso_14001(standard=None, standard_text="ISO 9001:2015"))["ACCEPTED_STANDARD"]

    assert not passed
    assert "ISO 9001:2015" in detail


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"valid_until": date(2026, 10, 15)}, "Venció el 2026-10-15"),
        ({"valid_until": None}, "El certificado no indica fecha de vencimiento"),
        ({"issued_on": date(2026, 10, 17)}, "La fecha de emisión (2026-10-17) es futura"),
    ],
)
def test_a_certificate_out_of_force_fails(changes: dict[str, object], expected: str) -> None:
    assert results(iso_14001(**changes))["IN_FORCE"] == (False, expected)


def test_a_certificate_that_expires_today_is_still_in_force() -> None:
    assert results(iso_14001(valid_until=TODAY))["IN_FORCE"][0]


@pytest.mark.parametrize(
    ("extraction", "standing", "expected"),
    [
        (iso_14001(holder_name="Otra Empresa S.A.C."), STANDING, "no coincide"),
        (iso_14001(holder_name=None), STANDING, "no indica a qué empresa"),
        (iso_14001(holder_ruc="RUC 20100002621"), STANDING, "es del RUC 20100002621"),
        (iso_14001(), replace(STANDING, registered_name=None), "no figura en el padrón"),
        (iso_14001(), replace(STANDING, registry_loaded=False), "No se pudo consultar el padrón"),
    ],
)
def test_a_holder_that_is_not_the_mype_fails(
    extraction: CertificateExtraction, standing: CompanyStanding, expected: str
) -> None:
    passed, detail = results(extraction, standing)["HOLDER_MATCHES_SUNAT"]

    assert not passed
    assert expected in detail


def test_the_holder_ruc_may_be_printed_with_separators() -> None:
    assert results(iso_14001(holder_ruc="RUC: 20601234567"))["HOLDER_MATCHES_SUNAT"][0]


def test_an_environmental_offender_fails_and_an_unloaded_register_fails_too() -> None:
    offender = results(standing=replace(STANDING, environmental_infractions=2))["NOT_ENVIRONMENTAL_OFFENDER"]
    unloaded = results(standing=replace(STANDING, environmental_registry_loaded=False))["NOT_ENVIRONMENTAL_OFFENDER"]

    assert offender == (False, "Figura en el registro de infractores ambientales de OEFA (2 infracción(es))")
    assert not unloaded[0]


def test_one_failed_check_is_enough_to_not_be_green() -> None:
    criteria = policy.evaluate(iso_14001(valid_until=date(2020, 1, 1)), Ruc(RUC), STANDING, TODAY)

    assert not GreenCertificationPolicy.is_green(criteria)
