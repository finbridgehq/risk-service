"""The auction-lifecycle v1 contract, as this service reads it.

Investment publishes every change of an auction to one topic, in one envelope
(``eventId``, ``eventType``, ``schemaVersion``, ``aggregateId``, ``sequence``,
``occurredAt``, ``data``). The contract lives in Investment's repository, under
``docs/contracts/auction-lifecycle/v1``; this module mirrors only what this
service needs, and ignores fields it does not use so that Investment can add
optional ones without breaking it.

Parsing never raises: a message is either an ``AuctionCreated`` to apply, an
event this service does not need, or invalid, with the reason why.
"""
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

AUCTION_LIFECYCLE_TOPIC = "investment.auction-lifecycle.v1"
SCHEMA_VERSION = 1
AUCTION_CREATED = "AuctionCreated"
KNOWN_EVENT_TYPES = frozenset(
    {
        AUCTION_CREATED,
        "AuctionEvaluated",
        "AuctionRejected",
        "AuctionPublished",
        "PartitionAdded",
        "AuctionFullyFunded",
        "AuctionExpired",
        "AuctionCancelled",
        "AuctionClosed",
    }
)


class _ContractModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", frozen=True)


class AuctionLifecycleEnvelope(_ContractModel):
    """The envelope every auction-lifecycle event travels in."""

    event_id: UUID
    event_type: str = Field(min_length=1)
    schema_version: int
    aggregate_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    data: dict[str, Any]


class AuctionCreatedData(_ContractModel):
    """The ``data`` of an ``AuctionCreated`` event."""

    invoice_id: str = Field(min_length=1, max_length=64)
    mype_id: str = Field(min_length=1, max_length=64)
    payer_ruc: str
    payer_name: str
    due_date: date
    invoice_amount: Decimal
    currency: str
    status: str
    green_certified: bool


@dataclass(frozen=True, slots=True)
class AuctionCreatedMessage:
    """An ``AuctionCreated`` event to apply.

    Attributes:
        envelope (AuctionLifecycleEnvelope): Who, when and which event.
        data (AuctionCreatedData): What Investment published about the auction.
    """

    envelope: AuctionLifecycleEnvelope
    data: AuctionCreatedData


@dataclass(frozen=True, slots=True)
class IgnoredMessage:
    """A valid event of the contract that this service does not need.

    Attributes:
        event_type (str): Its name, e.g. ``AuctionPublished``.
    """

    event_type: str


@dataclass(frozen=True, slots=True)
class InvalidMessage:
    """A message that cannot be applied; it goes to the dead letters.

    Attributes:
        reason (str): A short, stable code, e.g. ``unknown-event-type``.
        error (str): What is wrong with it.
    """

    reason: str
    error: str


type ParsedMessage = AuctionCreatedMessage | IgnoredMessage | InvalidMessage


def parse_auction_lifecycle_message(raw: bytes | None) -> ParsedMessage:
    """Read one message of the auction-lifecycle topic.

    An unknown event type or schema version is invalid, never skipped
    silently: the contract asks consumers not to process what they do not
    understand.

    Args:
        raw (bytes | None): The message value as Kafka delivered it.

    Returns:
        ParsedMessage: What the message is, and what to do with it.
    """
    if raw is None:
        return InvalidMessage("empty-message", "The message has no value")
    try:
        document = json.loads(raw, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return InvalidMessage("malformed-json", str(error))
    try:
        envelope = AuctionLifecycleEnvelope.model_validate(document)
    except ValidationError as error:
        return InvalidMessage("invalid-envelope", _describe(error))

    if envelope.schema_version != SCHEMA_VERSION:
        return InvalidMessage(
            "unsupported-schema-version",
            f"{envelope.event_type} has schemaVersion {envelope.schema_version}; this service reads {SCHEMA_VERSION}",
        )
    if envelope.event_type not in KNOWN_EVENT_TYPES:
        return InvalidMessage("unknown-event-type", f"'{envelope.event_type}' is not an auction-lifecycle v1 event")
    if envelope.event_type != AUCTION_CREATED:
        return IgnoredMessage(envelope.event_type)

    try:
        data = AuctionCreatedData.model_validate(envelope.data)
    except ValidationError as error:
        return InvalidMessage("invalid-data", _describe(error))
    return AuctionCreatedMessage(envelope, data)


def _describe(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors())
