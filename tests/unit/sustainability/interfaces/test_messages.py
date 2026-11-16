"""Reading Profile's events."""

import json
from pathlib import Path

import pytest

from sustainability.interfaces.messages import (
    CertificateSubmittedMessage,
    IgnoredMessage,
    InvalidMessage,
    parse_profile_message,
)

EXAMPLE = Path(__file__).resolve().parents[3] / "contracts" / "profile-events" / "v1"


def example(**changes: object) -> bytes:
    document = json.loads((EXAMPLE / "sustainability-certificate-submitted.json").read_text())
    document.update(changes)
    return json.dumps(document).encode()


def test_reads_the_contract_example() -> None:
    parsed = parse_profile_message(example())

    assert isinstance(parsed, CertificateSubmittedMessage)
    assert parsed.event.ruc_number == "20601234567"
    assert parsed.event.object_key.endswith(".pdf")
    assert parsed.event.occurred_at.tzinfo is not None


@pytest.mark.parametrize("event_type", ["ProfileCompleted", "KycVerified", "SomethingNew"])
def test_profiles_other_events_are_skipped(event_type: str) -> None:
    raw = json.dumps({"eventType": event_type, "companyId": "c"}).encode()

    assert parse_profile_message(raw) == IgnoredMessage(event_type)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "empty-message"),
        (b"{not json", "malformed-json"),
        (b"[1, 2]", "invalid-envelope"),
        (example(schemaVersion=2), "unsupported-schema-version"),
        (example(occurredAt="2026-10-16T18:00:00"), "invalid-data"),
        (example(submissionId=""), "invalid-data"),
    ],
)
def test_a_message_that_cannot_be_applied_is_invalid(raw: bytes | None, reason: str) -> None:
    parsed = parse_profile_message(raw)

    assert isinstance(parsed, InvalidMessage)
    assert parsed.reason == reason
