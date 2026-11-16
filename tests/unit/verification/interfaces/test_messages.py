"""Reading Profile's verification requests."""

import json
from pathlib import Path

import pytest

from verification.interfaces.messages import (
    IgnoredMessage,
    InvalidMessage,
    VerificationRequestedMessage,
    parse_profile_message,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "contracts" / "profile-events" / "v1"


def example(**changes: object) -> bytes:
    document = json.loads((EXAMPLE / "company-verification-requested.json").read_text())
    document.update(changes)
    return json.dumps(document).encode()


def test_reads_the_contract_example() -> None:
    parsed = parse_profile_message(example())

    assert isinstance(parsed, VerificationRequestedMessage)
    assert parsed.event.request_id == "70000000-0000-4000-8000-000000000001"
    assert parsed.event.ruc_document_key.endswith(".pdf")
    assert parsed.event.occurred_at.tzinfo is not None


def test_skips_profiles_other_events() -> None:
    assert parse_profile_message(example(eventType="SustainabilityCertificateSubmitted")) == IgnoredMessage(
        "SustainabilityCertificateSubmitted"
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "empty-message"),
        (b"{not json", "malformed-json"),
        (b"[]", "invalid-envelope"),
        (example(schemaVersion=2), "unsupported-schema-version"),
        (example(requestId=""), "invalid-data"),
        (example(occurredAt="2026-10-29T18:00:00"), "invalid-data"),
    ],
)
def test_invalid_messages_say_why(raw: bytes | None, reason: str) -> None:
    parsed = parse_profile_message(raw)

    assert isinstance(parsed, InvalidMessage)
    assert parsed.reason == reason
