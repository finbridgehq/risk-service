"""Test data for the Sustainability context: the green MYPE and a valid certificate of it."""

from datetime import UTC, date, datetime
from typing import Any

from registries.interfaces.acl import PayerStandingRecord
from sustainability.domain.value_objects import CertificateExtraction, GreenStandard

NOW = datetime(2026, 10, 16, 18, 0, tzinfo=UTC)
TODAY = date(2026, 10, 16)
COMPANY_ID = "50000000-0000-4000-8000-000000000001"
USER_ID = "40000000-0000-4000-8000-000000000001"
RUC = "20601234567"
OBJECT_KEY = f"companies/{COMPANY_ID}/sustainability/60000000-0000-4000-8000-000000000001.pdf"

GREEN_MYPE = PayerStandingRecord(
    registry_loaded=True,
    found=True,
    name="AGROEXPORT VERDE SOCIEDAD ANONIMA CERRADA",
    status="ACTIVO",
    domicile_condition="HABIDO",
)


def iso_14001(**overrides: Any) -> CertificateExtraction:
    """What a reader finds in a valid ISO 14001 certificate of the green MYPE, unless overridden."""
    values: dict[str, Any] = {
        "is_certificate": True,
        "standard": GreenStandard.ISO_14001,
        "standard_text": "ISO 14001:2015",
        "issuer": "SGS del Perú S.A.C.",
        "holder_name": "Agroexport Verde S.A.C.",
        "holder_ruc": None,
        "issued_on": date(2025, 4, 1),
        "valid_until": date(2028, 3, 31),
        "scope": "Exportación de palta fresca",
    }
    values.update(overrides)
    return CertificateExtraction(**values)
