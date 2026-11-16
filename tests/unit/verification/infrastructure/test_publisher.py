"""The CompanyVerificationIssued message, against the contract example."""

import json
from pathlib import Path

from tests.kyc_data import signed_by_sunat
from tests.kyc_fakes import FakeInspector, build_kyc_service, verification_requested
from verification.infrastructure.publisher import to_message

CONTRACT = Path(__file__).resolve().parents[4] / "docs" / "contracts" / "company-verifications" / "v1"


async def test_the_message_has_the_shape_of_the_contract_example() -> None:
    sut = build_kyc_service(inspector=FakeInspector(signed_by_sunat(issued_on=None)))
    verification = await sut.service.verify_company(**verification_requested())
    assert verification is not None

    message = to_message(verification, "91000000-0000-4000-8000-000000000001", verification.decided_at)
    example = json.loads((CONTRACT / "company-verification-issued.json").read_text())

    assert message.keys() == example.keys()
    assert message["data"].keys() == example["data"].keys()
    assert message["data"]["checks"][0].keys() == example["data"]["checks"][0].keys()
    assert [check["code"] for check in message["data"]["checks"]] == [
        check["code"] for check in example["data"]["checks"]
    ]
    assert message["occurredAt"] == "2026-10-29T18:00:00.000Z"
    assert message["data"]["decision"] == "REJECTED"
    assert message["data"]["reasonCodes"] == ["RUC_DOCUMENT_RECENT"]
