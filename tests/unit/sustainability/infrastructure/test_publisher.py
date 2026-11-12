"""The GreenCertificationIssued message, against the contract example."""

import json
from pathlib import Path

from sustainability.infrastructure.publisher import to_message
from tests.green_data import iso_14001
from tests.green_fakes import build_green_service, certificate_submitted

CONTRACT = Path(__file__).resolve().parents[4] / "docs" / "contracts" / "green-certifications" / "v1"


async def test_the_message_has_the_shape_of_the_contract_example() -> None:
    sut = build_green_service()
    certification = await sut.service.decide_on_certificate(**certificate_submitted())
    assert certification is not None

    message = to_message(certification, "90000000-0000-4000-8000-000000000001", certification.decided_at)
    example = json.loads((CONTRACT / "green-certification-issued.json").read_text())

    assert message.keys() == example.keys()
    assert message["data"].keys() == example["data"].keys()
    assert message["data"]["criteria"][0].keys() == example["data"]["criteria"][0].keys()
    assert message["occurredAt"] == "2026-10-16T18:00:00.000Z"
    assert message["data"]["standard"] == "ISO_14001"
    assert message["data"]["validUntil"] == "2028-03-31"


async def test_a_not_green_decision_lists_the_failed_checks() -> None:
    sut = build_green_service()
    sut.reader.extraction = iso_14001(standard=None, standard_text="ISO 9001:2015")
    certification = await sut.service.decide_on_certificate(**certificate_submitted())
    assert certification is not None

    data = to_message(certification, "event", certification.decided_at)["data"]

    assert data["decision"] == "NOT_GREEN"
    assert data["standard"] is None
    assert data["reasonCodes"] == ["ACCEPTED_STANDARD"]
