"""The outbox relay: what it sends, in which order, and what a failure does."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from aiokafka.errors import KafkaConnectionError

from shared.infrastructure.outbox import OutboxMessageModel, SqlAlchemyOutbox
from shared.infrastructure.settings import KafkaSettings
from shared.interfaces.outbox_relay import KafkaOutboxRelay

NOW = datetime(2026, 10, 16, 18, 0, tzinfo=UTC)


def message(number: int) -> OutboxMessageModel:
    return OutboxMessageModel(
        id=number,
        event_id=f"event-{number}",
        event_type="GreenCertificationIssued",
        topic="risk.green-certifications.v1",
        message_key=f"company-{number}",
        payload={"eventId": f"event-{number}", "data": {"detail": "Vigente hasta el 2028-03-31"}},
        attempts=0,
        next_attempt_at=NOW,
    )


class FakeProducer:
    """Records what it sends; fails on the topics' messages it is told to."""

    def __init__(self, fail_on: set[bytes] | None = None) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail_on = fail_on or set()

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        if key in self.fail_on:
            raise KafkaConnectionError("broker down")
        self.sent.append((topic, key, value))


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def relay_with(
    due: list[OutboxMessageModel], producer: FakeProducer, monkeypatch: pytest.MonkeyPatch
) -> tuple[KafkaOutboxRelay, list[FakeSession]]:
    sessions: list[FakeSession] = []

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[FakeSession]:
        session = FakeSession()
        sessions.append(session)
        yield session

    async def find_due(self: SqlAlchemyOutbox, now: datetime, limit: int) -> list[OutboxMessageModel]:
        return [model for model in due if model.sent_at is None and model.next_attempt_at <= now][:limit]

    monkeypatch.setattr(SqlAlchemyOutbox, "find_due", find_due)
    relay = KafkaOutboxRelay(KafkaSettings(), cast(Any, session_factory), clock=lambda: NOW)
    relay._producer = cast(Any, producer)
    return relay, sessions


async def test_sends_the_due_messages_in_order_and_marks_them_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    due = [message(1), message(2)]
    producer = FakeProducer()
    relay, sessions = relay_with(due, producer, monkeypatch)

    assert await relay.relay_due() == 2

    assert [key for _, key, _ in producer.sent] == [b"company-1", b"company-2"]
    topic, _, value = producer.sent[0]
    assert topic == "risk.green-certifications.v1"
    assert json.loads(value)["data"]["detail"] == "Vigente hasta el 2028-03-31"
    assert all(model.sent_at == NOW and model.attempts == 1 for model in due)
    assert sessions[0].commits == 1


async def test_stops_at_a_failure_and_waits_longer_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    due = [message(1), message(2)]
    relay, _ = relay_with(due, FakeProducer(fail_on={b"company-1"}), monkeypatch)

    assert await relay.relay_due() == 0

    failed, untouched = due
    assert failed.sent_at is None
    assert failed.next_attempt_at == NOW + timedelta(seconds=1)
    assert "broker down" in (failed.last_error or "")
    assert untouched.attempts == 0
    SqlAlchemyOutbox.mark_failed(failed, "again", NOW)
    assert failed.next_attempt_at == NOW + timedelta(seconds=2)


def test_the_wait_never_exceeds_five_minutes() -> None:
    model = message(1)
    model.attempts = 30

    SqlAlchemyOutbox.mark_failed(model, "down", NOW)

    assert model.next_attempt_at == NOW + timedelta(minutes=5)
