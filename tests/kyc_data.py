"""Test data for the Verification context: a MYPE, its signed ficha RUC and its standing."""

from datetime import UTC, date, datetime
from typing import Any

from registries.interfaces.acl import PayerStandingRecord
from verification.domain.value_objects import (
    Applicant,
    Ruc,
    RucDocumentFacts,
    RucDocumentInspection,
    SignatureAuthority,
    TaxpayerStanding,
)

NOW = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
TODAY = date(2026, 10, 29)
COMPANY_ID = "50000000-0000-4000-8000-000000000002"
USER_ID = "40000000-0000-4000-8000-000000000002"
REQUEST_ID = "70000000-0000-4000-8000-000000000001"
RUC = "20601234567"
BUSINESS_NAME = "Textiles Andinos S.A.C."
REGISTERED_NAME = "TEXTILES ANDINOS SOCIEDAD ANONIMA CERRADA"
OBJECT_KEY = f"companies/{COMPANY_ID}/ruc/60000000-0000-4000-8000-000000000002.pdf"

APPLICANT = Applicant(company_id=COMPANY_ID, user_id=USER_ID, ruc=Ruc(RUC), business_name=BUSINESS_NAME)

ACTIVE_TAXPAYER = PayerStandingRecord(
    registry_loaded=True,
    found=True,
    name=REGISTERED_NAME,
    status="ACTIVO",
    domicile_condition="HABIDO",
)


def standing(**overrides: Any) -> TaxpayerStanding:
    """What the registries say about the MYPE: an active, found taxpayer, unless overridden."""
    values: dict[str, Any] = {
        "registry_loaded": True,
        "shell_registry_loaded": True,
        "found": True,
        "registered_name": REGISTERED_NAME,
        "status": "ACTIVO",
        "domicile_condition": "HABIDO",
    }
    values.update(overrides)
    return TaxpayerStanding(**values)


def facts(**overrides: Any) -> RucDocumentFacts:
    """What a recent ficha RUC of the MYPE says, unless overridden."""
    values: dict[str, Any] = {
        "ruc": RUC,
        "name": "TEXTILES ANDINOS S.A.C.",
        "status": "ACTIVO",
        "domicile_condition": "HABIDO",
        "issued_on": date(2026, 10, 27),
    }
    values.update(overrides)
    return RucDocumentFacts(**values)


def signed_by_sunat(**overrides: Any) -> RucDocumentInspection:
    """A ficha RUC of the MYPE signed by SUNAT, with its facts overridden."""
    return RucDocumentInspection(authority=SignatureAuthority.SUNAT, facts=facts(**overrides))
