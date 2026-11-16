"""The parser reads what Investment publishes, from the contract's own examples."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from assessments.interfaces.messages import (
    AuctionCreatedMessage,
    IgnoredMessage,
    InvalidMessage,
    parse_auction_lifecycle_message,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "auction-lifecycle" / "v1"


def example(name: str) -> dict[str, object]:
    document: dict[str, object] = json.loads((EXAMPLES / f"{name}.json").read_text())
    return document


def encode(document: object) -> bytes:
    return json.dumps(document).encode()


def test_auction_created_example_is_read() -> None:
    parsed = parse_auction_lifecycle_message((EXAMPLES / "auction-created.json").read_bytes())
    assert isinstance(parsed, AuctionCreatedMessage)
    assert str(parsed.envelope.event_id) == "10000000-0000-4000-8000-000000000001"
    assert parsed.envelope.aggregate_id == "20000000-0000-4000-8000-000000000001"
    assert parsed.data.payer_ruc == "20123456789"
    assert parsed.data.invoice_amount == Decimal("10000.00")
    assert parsed.data.green_certified is True


@pytest.mark.parametrize(
    "name",
    [
        "auction-evaluated",
        "auction-rejected",
        "auction-published",
        "partition-added",
        "auction-fully-funded",
        "auction-expired",
        "auction-cancelled",
        "auction-closed",
    ],
)
def test_other_contract_events_are_ignored(name: str) -> None:
    parsed = parse_auction_lifecycle_message((EXAMPLES / f"{name}.json").read_bytes())
    assert isinstance(parsed, IgnoredMessage)


def test_fractional_seconds_and_unknown_fields_are_accepted() -> None:
    document = example("auction-created")
    document["occurredAt"] = "2026-09-14T15:00:00.123456Z"
    document["traceId"] = "added-later"
    parsed = parse_auction_lifecycle_message(encode(document))
    assert isinstance(parsed, AuctionCreatedMessage)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"schemaVersion": 2}, "unsupported-schema-version"),
        ({"eventType": "AuctionRepriced"}, "unknown-event-type"),
        ({"eventId": "not-a-uuid"}, "invalid-envelope"),
        ({"sequence": 0}, "invalid-envelope"),
        ({"occurredAt": "2026-09-14T15:00:00"}, "invalid-envelope"),
        ({"data": {"invoiceId": "only-this"}}, "invalid-data"),
    ],
)
def test_messages_this_service_cannot_apply_are_invalid(change: dict[str, object], reason: str) -> None:
    document = example("auction-created")
    document.update(change)
    parsed = parse_auction_lifecycle_message(encode(document))
    assert isinstance(parsed, InvalidMessage)
    assert parsed.reason == reason


@pytest.mark.parametrize(("raw", "reason"), [(None, "empty-message"), (b"{not json", "malformed-json")])
def test_unreadable_messages_are_invalid(raw: bytes | None, reason: str) -> None:
    parsed = parse_auction_lifecycle_message(raw)
    assert isinstance(parsed, InvalidMessage)
    assert parsed.reason == reason
