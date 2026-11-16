"""What the consumer of Profile's events does with each kind of message."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from shared.infrastructure.messaging import DeadLetterModel
from shared.infrastructure.settings import KafkaSettings
from sustainability.application.outbound_services import TemporarilyUnavailableError
from sustainability.interfaces.consumers import ProfileEventsConsumer
from tests.green_fakes import FakeReader, GreenServiceUnderTest, build_green_service
from tests.unit.assessments.interfaces.test_consumers import FakeSession

EXAMPLE = Path(__file__).resolve().parents[3] / "contracts" / "profile-events" / "v1"
TOPIC = "vankoo.profile.events"


class Harness:
    """A consumer wired to in-memory fakes."""

    def __init__(self, reader: FakeReader | None = None) -> None:
        self.sut: GreenServiceUnderTest = build_green_service(reader=reader)
        self.sessions: list[FakeSession] = []

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[FakeSession]:
            session = FakeSession()
            self.sessions.append(session)
            yield session

        self.consumer = ProfileEventsConsumer(
            KafkaSettings(), "risk-profile-sustainability-v1", cast(Any, session_factory), lambda s: self.sut.service
        )

    @property
    def dead_letters(self) -> list[DeadLetterModel]:
        return [item for session in self.sessions for item in session.added if isinstance(item, DeadLetterModel)]

    async def deliver(self, value: bytes | None) -> None:
        await self.consumer.handle(topic=TOPIC, partition=0, offset=3, key=b"company-1", value=value)


def example(**changes: object) -> bytes:
    document = json.loads((EXAMPLE / "sustainability-certificate-submitted.json").read_text())
    document.update(changes)
    return json.dumps(document).encode()


async def test_a_submitted_certificate_is_decided() -> None:
    harness = Harness()

    await harness.deliver(example())

    [certification] = harness.sut.repository.rows
    assert certification.submission_id == "80000000-0000-4000-8000-000000000001"
    assert certification.mype.user_id == "40000000-0000-4000-8000-000000000001"
    assert harness.dead_letters == []


async def test_profiles_other_events_change_nothing() -> None:
    harness = Harness()

    await harness.deliver(json.dumps({"eventType": "KycVerified", "companyId": "c"}).encode())

    assert harness.sut.repository.rows == []
    assert harness.dead_letters == []


async def test_a_key_outside_the_sustainability_folder_is_dead_lettered() -> None:
    harness = Harness()

    await harness.deliver(example(objectKey="companies/x/ruc/secret.pdf"))

    [letter] = harness.dead_letters
    assert letter.reason == "rejected-by-domain"
    assert harness.sut.repository.rows == []


async def test_a_model_that_does_not_answer_propagates_so_the_message_is_retried() -> None:
    harness = Harness(reader=FakeReader(TemporarilyUnavailableError("timeout")))

    with pytest.raises(TemporarilyUnavailableError):
        await harness.deliver(example())

    assert harness.dead_letters == []
