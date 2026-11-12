"""What the consumer of Profile's verification requests does with each kind of message."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from shared.infrastructure.messaging import DeadLetterModel
from shared.infrastructure.settings import KafkaSettings
from tests.kyc_fakes import FakeRucDocuments, KycServiceUnderTest, build_kyc_service
from tests.unit.assessments.interfaces.test_consumers import FakeSession
from verification.application.outbound_services import TemporarilyUnavailableError
from verification.interfaces.consumers import VerificationRequestsConsumer

EXAMPLE = Path(__file__).resolve().parents[3] / "contracts" / "profile-events" / "v1"
TOPIC = "vankoo.profile.events"


class Harness:
    """A consumer wired to in-memory fakes."""

    def __init__(self, documents: FakeRucDocuments | None = None) -> None:
        self.sut: KycServiceUnderTest = build_kyc_service(documents=documents)
        self.sessions: list[FakeSession] = []

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[FakeSession]:
            session = FakeSession()
            self.sessions.append(session)
            yield session

        self.consumer = VerificationRequestsConsumer(
            KafkaSettings(), "risk-profile-verification-v1", cast(Any, session_factory), lambda s: self.sut.service
        )

    @property
    def dead_letters(self) -> list[DeadLetterModel]:
        return [item for session in self.sessions for item in session.added if isinstance(item, DeadLetterModel)]

    async def deliver(self, value: bytes | None) -> None:
        await self.consumer.handle(topic=TOPIC, partition=0, offset=3, key=b"company-1", value=value)


def example(**changes: object) -> bytes:
    document = json.loads((EXAMPLE / "company-verification-requested.json").read_text())
    document.update(changes)
    return json.dumps(document).encode()


async def test_a_request_is_verified() -> None:
    harness = Harness()

    await harness.deliver(example())

    [verification] = harness.sut.repository.rows
    assert verification.request_id == "70000000-0000-4000-8000-000000000001"
    assert verification.applicant.user_id == "40000000-0000-4000-8000-000000000002"
    assert harness.dead_letters == []


async def test_profiles_other_events_change_nothing() -> None:
    harness = Harness()

    await harness.deliver(json.dumps({"eventType": "SustainabilityCertificateSubmitted"}).encode())

    assert harness.sut.repository.rows == []
    assert harness.dead_letters == []


async def test_a_key_outside_the_ruc_folder_is_dead_lettered() -> None:
    harness = Harness()

    await harness.deliver(example(rucDocumentKey="companies/x/sustainability/secret.pdf"))

    [letter] = harness.dead_letters
    assert letter.reason == "rejected-by-domain"
    assert harness.sut.repository.rows == []


async def test_a_storage_that_does_not_answer_propagates_so_the_message_is_retried() -> None:
    harness = Harness(documents=FakeRucDocuments(TemporarilyUnavailableError("timeout")))

    with pytest.raises(TemporarilyUnavailableError):
        await harness.deliver(example())

    assert harness.dead_letters == []
