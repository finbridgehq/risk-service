"""The use cases of Sustainability, on in-memory fakes."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from shared.domain.exceptions import DomainError
from sustainability.application.acl import ExternalRegistriesService
from sustainability.application.outbound_services import (
    CertificateUnreadableError,
    DocumentRejectedError,
    TemporarilyUnavailableError,
)
from sustainability.application.services import GreenCertificationQueryService
from sustainability.domain.events import GreenCertificationDecided
from sustainability.domain.value_objects import GreenDecision, GreenStatusCode
from tests.fakes import FakeRegistriesFacade
from tests.green_data import GREEN_MYPE, NOW, TODAY, USER_ID, iso_14001
from tests.green_fakes import FakeDocuments, FakeReader, build_green_service, certificate_submitted


async def test_a_valid_certificate_is_green_and_its_decision_waits_in_the_outbox() -> None:
    sut = build_green_service()
    woken: list[GreenCertificationDecided] = []

    async def remember(event: object) -> None:
        assert isinstance(event, GreenCertificationDecided)
        woken.append(event)

    sut.event_bus.subscribe(GreenCertificationDecided, remember)

    certification = await sut.service.decide_on_certificate(**certificate_submitted())

    assert certification is not None
    assert certification.decision is GreenDecision.GREEN
    assert sut.unit_of_work.commits == 1
    [message] = sut.outbox.messages
    assert message.topic == "risk.green-certifications.v1"
    assert message.key == certification.mype.company_id
    assert message.payload["data"]["decision"] == "GREEN"
    assert message.payload["data"]["submissionId"] == "80000000-0000-4000-8000-000000000001"
    assert message.payload["data"]["reasonCodes"] == []
    assert [event.decision for event in woken] == ["GREEN"]


async def test_a_redelivered_event_is_applied_once() -> None:
    sut = build_green_service()
    await sut.service.decide_on_certificate(**certificate_submitted())

    again = await sut.service.decide_on_certificate(**certificate_submitted())

    assert again is None
    assert sut.reader.reads == 1
    assert len(sut.outbox.messages) == 1


async def test_another_event_about_an_upload_already_decided_returns_that_decision() -> None:
    sut = build_green_service()
    first = await sut.service.decide_on_certificate(**certificate_submitted())

    second = await sut.service.decide_on_certificate(**certificate_submitted(event_id="other-event"))

    assert second is not None and first is not None
    assert second.certification_id == first.certification_id
    assert len(sut.outbox.messages) == 1


async def test_without_a_reader_the_upload_stays_undecided() -> None:
    sut = build_green_service(reader=FakeReader(is_active=False))

    assert await sut.service.decide_on_certificate(**certificate_submitted()) is None
    assert sut.repository.rows == []
    assert sut.outbox.messages == []
    assert await sut.inbox.has_processed("70000000-0000-4000-8000-000000000001")


async def test_a_file_that_cannot_be_used_is_not_green_and_says_why() -> None:
    sut = build_green_service(
        documents=FakeDocuments(DocumentRejectedError("No se encontró el archivo del certificado"))
    )

    certification = await sut.service.decide_on_certificate(**certificate_submitted())

    assert certification is not None
    assert certification.decision is GreenDecision.NOT_GREEN
    assert [(r.code.value, r.detail) for r in certification.criteria] == [
        ("CERTIFICATE_READABLE", "No se encontró el archivo del certificado")
    ]
    assert sut.outbox.messages[0].payload["data"]["reasonCodes"] == ["CERTIFICATE_READABLE"]


async def test_an_unusable_answer_of_the_reader_is_not_green() -> None:
    sut = build_green_service(reader=FakeReader(CertificateUnreadableError("truncated JSON")))

    certification = await sut.service.decide_on_certificate(**certificate_submitted())

    assert certification is not None
    assert certification.decision is GreenDecision.NOT_GREEN
    assert certification.extraction is None


@pytest.mark.parametrize("where", ["documents", "reader"])
async def test_a_dependency_that_does_not_answer_stores_nothing_so_the_event_can_be_retried(where: str) -> None:
    failure = TemporarilyUnavailableError("timeout")
    sut = build_green_service(
        documents=FakeDocuments(failure) if where == "documents" else None,
        reader=FakeReader(failure) if where == "reader" else None,
    )

    with pytest.raises(TemporarilyUnavailableError):
        await sut.service.decide_on_certificate(**certificate_submitted())

    assert sut.repository.rows == []
    assert sut.unit_of_work.commits == 0
    assert not await sut.inbox.has_processed("70000000-0000-4000-8000-000000000001")


async def test_an_offender_in_oefa_is_not_green() -> None:
    sut = build_green_service(standing=replace(GREEN_MYPE, environmental_infractions=3))

    certification = await sut.service.decide_on_certificate(**certificate_submitted())

    assert certification is not None
    assert certification.decision is GreenDecision.NOT_GREEN


@pytest.mark.parametrize(
    "changes",
    [
        {"ruc": "123"},
        {"content_type": "text/html"},
        {"object_key": "companies/x/ruc/secret.pdf"},
        {"submitted_at": NOW.replace(tzinfo=None)},
    ],
)
async def test_unacceptable_facts_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(DomainError):
        await build_green_service().service.decide_on_certificate(**certificate_submitted(**changes))


async def test_the_status_follows_the_latest_decided_certificate() -> None:
    sut = build_green_service()
    queries = GreenCertificationQueryService(
        sut.repository,
        ExternalRegistriesService(FakeRegistriesFacade(GREEN_MYPE)),  # type: ignore[arg-type]
    )
    assert (await queries.get_green_status(USER_ID, TODAY)).code is GreenStatusCode.NO_CERTIFICATE

    await sut.service.decide_on_certificate(**certificate_submitted())
    green = await queries.get_green_status(USER_ID, TODAY)
    assert green.code is GreenStatusCode.GREEN
    assert (await queries.get_green_status(USER_ID, date(2028, 4, 1))).code is GreenStatusCode.EXPIRED

    sut.reader.extraction = iso_14001(holder_name="Otra Empresa S.A.C.")
    await sut.service.decide_on_certificate(
        **certificate_submitted(
            event_id="event-2",
            submission_id="submission-2",
            submitted_at=NOW + timedelta(days=1),
            object_key="companies/50000000-0000-4000-8000-000000000001/sustainability/"
            "60000000-0000-4000-8000-000000000002.pdf",
        )
    )
    assert (await queries.get_green_status(USER_ID, TODAY)).code is GreenStatusCode.NOT_GREEN


async def test_a_green_mype_that_enters_oefa_later_stops_being_green() -> None:
    sut = build_green_service()
    await sut.service.decide_on_certificate(**certificate_submitted())
    queries = GreenCertificationQueryService(
        sut.repository,
        ExternalRegistriesService(FakeRegistriesFacade(replace(GREEN_MYPE, environmental_infractions=1))),  # type: ignore[arg-type]
    )

    assert (await queries.get_green_status(USER_ID, TODAY)).code is GreenStatusCode.ENVIRONMENTAL_OFFENDER
