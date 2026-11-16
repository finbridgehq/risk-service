"""Profile's events, as this service reads them.

Profile publishes every event of a profile to ``vankoo.profile.events`` as a
flat JSON object with an ``eventType``. Only ``SustainabilityCertificateSubmitted``
matters here; it is versioned (``schemaVersion`` 1) and carries an
``eventId``. Profile's other events (``ProfileCompleted``, ``KycVerified``…)
and any new one are skipped: the topic is Profile's, not this service's. Its
contract lives in Profile's repository, under ``docs/``.

Parsing never raises.
"""
import json
from dataclasses import dataclass

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

PROFILE_EVENTS_TOPIC = "vankoo.profile.events"
CERTIFICATE_SUBMITTED = "SustainabilityCertificateSubmitted"
SCHEMA_VERSION = 1


class CertificateSubmittedEvent(BaseModel):
    """A MYPE uploaded a sustainability certificate to its profile."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", frozen=True)

    event_id: str = Field(min_length=1, max_length=64)
    event_type: str
    schema_version: int
    occurred_at: AwareDatetime
    submission_id: str = Field(min_length=1, max_length=64)
    company_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    ruc_number: str
    business_name: str
    object_key: str
    content_type: str


@dataclass(frozen=True, slots=True)
class CertificateSubmittedMessage:
    """A ``SustainabilityCertificateSubmitted`` event to apply.

    Attributes:
        event (CertificateSubmittedEvent): What Profile published.
    """

    event: CertificateSubmittedEvent


@dataclass(frozen=True, slots=True)
class IgnoredMessage:
    """Another of Profile's events, which this service does not need.

    Attributes:
        event_type (str): Its name, e.g. ``KycVerified``.
    """

    event_type: str


@dataclass(frozen=True, slots=True)
class InvalidMessage:
    """A message that cannot be applied; it goes to the dead letters.

    Attributes:
        reason (str): A short, stable code, e.g. ``malformed-json``.
        error (str): What is wrong with it.
    """

    reason: str
    error: str


type ParsedMessage = CertificateSubmittedMessage | IgnoredMessage | InvalidMessage


def parse_profile_message(raw: bytes | None) -> ParsedMessage:
    """Read one message of Profile's topic.

    Args:
        raw (bytes | None): The message value as Kafka delivered it.

    Returns:
        ParsedMessage: What the message is, and what to do with it.
    """
    if raw is None:
        return InvalidMessage("empty-message", "The message has no value")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return InvalidMessage("malformed-json", str(error))
    if not isinstance(document, dict) or not isinstance(document.get("eventType"), str):
        return InvalidMessage("invalid-envelope", "The message is not an object with an eventType")
    if document["eventType"] != CERTIFICATE_SUBMITTED:
        return IgnoredMessage(document["eventType"])
    if document.get("schemaVersion") != SCHEMA_VERSION:
        return InvalidMessage(
            "unsupported-schema-version",
            f"{CERTIFICATE_SUBMITTED} has schemaVersion {document.get('schemaVersion')}; "
            f"this service reads {SCHEMA_VERSION}",
        )
    try:
        return CertificateSubmittedMessage(CertificateSubmittedEvent.model_validate(document))
    except ValidationError as error:
        return InvalidMessage(
            "invalid-data",
            "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()),
        )
