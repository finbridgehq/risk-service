"""What the consumer does with each kind of message."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from assessments.interfaces.consumers import AuctionLifecycleConsumer
from shared.infrastructure.messaging import DeadLetterModel
from shared.infrastructure.settings import KafkaSettings
from tests.fakes import ServiceUnderTest, build_service

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "auction-lifecycle" / "v1"
TOPIC = "investment.auction-lifecycle.v1"


class FakeSession:
    """Just enough of an AsyncSession for the dead-letter store."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class Harness:
    """A consumer wired to in-memory fakes."""

    def __init__(self) -> None:
        self.sut: ServiceUnderTest = build_service()
        self.sessions: list[FakeSession] = []

        @asynccontextmanager
        async def session_factory() -> AsyncIterator[FakeSession]:
            session = FakeSession()
            self.sessions.append(session)
            yield session

        self.consumer = AuctionLifecycleConsumer(
            KafkaSettings(), cast(Any, session_factory), lambda session: self.sut.service
        )

    @property
    def dead_letters(self) -> list[DeadLetterModel]:
        return [item for session in self.sessions for item in session.added if isinstance(item, DeadLetterModel)]

    async def deliver(self, value: bytes | None, offset: int = 7) -> None:
        await self.consumer.handle(topic=TOPIC, partition=0, offset=offset, key=b"auction-1", value=value)


async def test_auction_created_is_assessed() -> None:
    harness = Harness()
    await harness.deliver((EXAMPLES / "auction-created.json").read_bytes())
    [assessment] = harness.sut.repository.rows.values()
    assert assessment.facts.auction_id.value == "20000000-0000-4000-8000-000000000001"
    assert harness.dead_letters == []


async def test_other_events_change_nothing() -> None:
    harness = Harness()
    await harness.deliver((EXAMPLES / "auction-published.json").read_bytes())
    assert harness.sut.repository.rows == {}
    assert harness.dead_letters == []


async def test_unreadable_messages_are_dead_lettered() -> None:
    harness = Harness()
    await harness.deliver(b"{not json", offset=42)
    [letter] = harness.dead_letters
    assert letter.reason == "malformed-json"
    assert letter.offset == 42
    assert letter.payload == "{not json"
    assert letter.message_key == "auction-1"
    assert harness.sessions[-1].commits == 1


async def test_facts_the_domain_refuses_are_dead_lettered() -> None:
    harness = Harness()
    raw = (EXAMPLES / "auction-created.json").read_text().replace('"20123456789"', '"123"')
    await harness.deliver(raw.encode())
    [letter] = harness.dead_letters
    assert letter.reason == "rejected-by-domain"
    assert "RUC" in letter.error
    assert harness.sut.repository.rows == {}


async def test_unexpected_failures_propagate_so_the_message_is_retried() -> None:
    harness = Harness()

    async def broken(*args: object, **kwargs: object) -> None:
        raise ConnectionError("database is down")

    harness.sut.service.assess_auction = broken  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await harness.deliver((EXAMPLES / "auction-created.json").read_bytes())
    assert harness.dead_letters == []
