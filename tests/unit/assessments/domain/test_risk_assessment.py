"""The assessment's rules: issued once, delivered once, retried with a growing wait."""
from datetime import datetime, timedelta

import pytest

from assessments.domain.entities import RiskAssessment
from assessments.domain.events import RiskAssessmentIssued
from assessments.domain.value_objects import AssessmentId, DeliveryStatus
from shared.domain.exceptions import ConflictError, DomainError
from tests.fakes import NOW, facts, graded


def issue(now: datetime = NOW) -> RiskAssessment:
    return RiskAssessment.issue(AssessmentId("risk-1"), facts(), graded(), "event-1", now)


def test_issue_schedules_delivery_now_and_records_the_event() -> None:
    assessment = issue()
    assert assessment.delivery_status is DeliveryStatus.PENDING
    assert assessment.next_delivery_at == NOW
    assert assessment.delivery_attempts == 0
    [event] = assessment.pull_events()
    assert isinstance(event, RiskAssessmentIssued)
    assert event.auction_id == assessment.facts.auction_id.value
    assert event.assessment_id == "risk-1"
    assert event.risk_grade == "B"


def test_issue_requires_a_time_zone() -> None:
    with pytest.raises(DomainError):
        issue(datetime(2026, 10, 14, 18, 0))


def test_delivered_assessment_is_settled() -> None:
    assessment = issue()
    assessment.mark_delivered(NOW, "DRAFT")
    assert assessment.delivery_status is DeliveryStatus.DELIVERED
    assert assessment.delivered_at == NOW
    assert assessment.next_delivery_at is None
    assert assessment.investment_auction_status == "DRAFT"
    assert assessment.delivery_attempts == 1
    with pytest.raises(ConflictError):
        assessment.mark_rejected("too late")
    with pytest.raises(ConflictError):
        assessment.record_delivery_failure("timeout", NOW)


def test_rejected_assessment_is_never_sent_again() -> None:
    assessment = issue()
    assessment.mark_rejected("HTTP 409: Auction can no longer be evaluated")
    assert assessment.delivery_status is DeliveryStatus.REJECTED
    assert assessment.next_delivery_at is None
    assert assessment.last_delivery_error == "HTTP 409: Auction can no longer be evaluated"
    with pytest.raises(ConflictError):
        assessment.mark_delivered(NOW, "DRAFT")


def test_failures_double_the_wait_up_to_five_minutes() -> None:
    assessment = issue()
    waits = []
    for _ in range(12):
        assessment.record_delivery_failure("connection refused", NOW)
        assert assessment.next_delivery_at is not None
        waits.append(assessment.next_delivery_at - NOW)
    assert waits[:4] == [timedelta(seconds=1), timedelta(seconds=2), timedelta(seconds=4), timedelta(seconds=8)]
    assert waits[-1] == timedelta(minutes=5)
    assert assessment.delivery_attempts == 12
    assert assessment.delivery_status is DeliveryStatus.PENDING


def test_errors_are_shortened() -> None:
    assessment = issue()
    assessment.record_delivery_failure("x" * 2000, NOW)
    assert assessment.last_delivery_error is not None
    assert len(assessment.last_delivery_error) == 500
