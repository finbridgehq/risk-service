"""The decision on a certificate: how it is made, what it keeps and whether it still holds later."""

from datetime import date, datetime

import pytest

from shared.domain.exceptions import DomainError
from sustainability.domain.entities import GreenCertification
from sustainability.domain.events import GreenCertificationDecided
from sustainability.domain.services import GreenCertificationPolicy
from sustainability.domain.value_objects import (
    CertificateDocument,
    CompanyStanding,
    CriterionCode,
    CriterionResult,
    DocumentType,
    GreenDecision,
    GreenStatusCode,
    Mype,
    Ruc,
)
from tests.green_data import COMPANY_ID, NOW, OBJECT_KEY, RUC, TODAY, USER_ID, iso_14001

MYPE = Mype(company_id=COMPANY_ID, user_id=USER_ID, ruc=Ruc(RUC), business_name="Agroexport Verde S.A.C.")
DOCUMENT = CertificateDocument(OBJECT_KEY, DocumentType.PDF)
STANDING = CompanyStanding(
    registry_loaded=True, registered_name="AGROEXPORT VERDE S.A.C.", environmental_registry_loaded=True
)


def decide(**changes: object) -> GreenCertification:
    extraction = iso_14001(**changes)
    return GreenCertification.decide(
        submission_id="submission-1",
        mype=MYPE,
        document=DOCUMENT,
        submitted_at=NOW,
        extraction=extraction,
        criteria=GreenCertificationPolicy().evaluate(extraction, MYPE.ruc, STANDING, TODAY),
        reader="fake-reader",
        source_event_id="event-1",
        now=NOW,
    )


def test_a_certificate_that_passes_every_check_is_green_and_records_the_decision() -> None:
    certification = decide()

    assert certification.decision is GreenDecision.GREEN
    assert certification.certification_id.value.startswith("green-")
    assert certification.rules_version == "green-v1"
    assert certification.valid_until == date(2028, 3, 31)
    [event] = certification.pull_events()
    assert isinstance(event, GreenCertificationDecided)
    assert (event.certification_id, event.company_id, event.decision) == (
        certification.certification_id.value,
        COMPANY_ID,
        "GREEN",
    )


def test_a_certificate_that_fails_a_check_is_not_green_but_keeps_every_check() -> None:
    certification = decide(holder_name="Otra S.A.C.")

    assert certification.decision is GreenDecision.NOT_GREEN
    assert len(certification.criteria) == 5
    assert [r.code for r in certification.criteria if not r.passed] == [CriterionCode.HOLDER_MATCHES_SUNAT]


def test_a_green_decision_cannot_be_rebuilt_without_its_facts_or_with_a_failed_check() -> None:
    failed = (CriterionResult(CriterionCode.IN_FORCE, False, "Venció"),)
    with pytest.raises(DomainError):
        GreenCertification(
            decide().certification_id, "s", MYPE, DOCUMENT, NOW, iso_14001(), failed,
            GreenDecision.GREEN, NOW, "r", "green-v1", "e",
        )  # fmt: skip
    with pytest.raises(DomainError):
        GreenCertification(
            decide().certification_id, "s", MYPE, DOCUMENT, NOW, None, decide().criteria,
            GreenDecision.GREEN, NOW, "r", "green-v1", "e",
        )  # fmt: skip


def test_a_decision_needs_aware_times_and_its_checks() -> None:
    with pytest.raises(DomainError, match="time zone"):
        GreenCertification(
            decide().certification_id, "s", MYPE, DOCUMENT, datetime(2026, 10, 16), None,
            decide(valid_until=None).criteria, GreenDecision.NOT_GREEN, NOW, "r", "green-v1", "e",
        )  # fmt: skip
    with pytest.raises(DomainError, match="checks"):
        GreenCertification(
            decide().certification_id, "s", MYPE, DOCUMENT, NOW, None, (),
            GreenDecision.NOT_GREEN, NOW, "r", "green-v1", "e",
        )  # fmt: skip


@pytest.mark.parametrize(
    ("today", "infractions", "expected"),
    [
        (TODAY, 0, GreenStatusCode.GREEN),
        (date(2028, 3, 31), 0, GreenStatusCode.GREEN),
        (date(2028, 4, 1), 0, GreenStatusCode.EXPIRED),
        (TODAY, 1, GreenStatusCode.ENVIRONMENTAL_OFFENDER),
    ],
)
def test_a_green_certificate_holds_while_in_force_and_out_of_oefa(
    today: date, infractions: int, expected: GreenStatusCode
) -> None:
    assert decide().status_on(today, infractions) is expected


def test_a_certificate_that_was_not_green_never_is() -> None:
    assert decide(valid_until=date(2020, 1, 1)).status_on(TODAY, 0) is GreenStatusCode.NOT_GREEN


@pytest.mark.parametrize(
    ("key", "document_type"),
    [
        ("companies/other/ruc/60000000-0000-4000-8000-000000000001.pdf", DocumentType.PDF),
        ("../../etc/passwd", DocumentType.PDF),
        (OBJECT_KEY, DocumentType.PNG),
        ("http://evil.example/" + OBJECT_KEY, DocumentType.PDF),
    ],
)
def test_only_a_key_in_a_sustainability_folder_with_its_extension_is_a_certificate(
    key: str, document_type: DocumentType
) -> None:
    with pytest.raises(DomainError):
        CertificateDocument(key, document_type)
