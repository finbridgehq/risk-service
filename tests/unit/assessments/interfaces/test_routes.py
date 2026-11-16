"""The read endpoint and the health endpoints, over ASGI."""
from collections.abc import AsyncIterator

import httpx
import pytest

from assessments.interfaces.dependencies import get_risk_assessment_service
from main import app
from tests.fakes import ServiceUnderTest, auction_created, build_service


@pytest.fixture
async def sut() -> AsyncIterator[ServiceUnderTest]:
    service = build_service()
    app.dependency_overrides[get_risk_assessment_service] = lambda: service.service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://risk") as http:
        yield http


async def test_reads_the_assessment_of_an_auction(sut: ServiceUnderTest, client: httpx.AsyncClient) -> None:
    await sut.service.assess_auction(**auction_created())

    response = await client.get("/api/v1/risk-assessments/20000000-0000-4000-8000-000000000001")

    assert response.status_code == 200
    body = response.json()
    assert body["assessment_id"].startswith("risk-")
    assert body["eligible"] is True
    assert body["risk_grade"] == "B"
    assert body["score"] == 60
    assert body["provisional"] is False
    assert body["grading_policy"] == "points-v3"
    assert {factor["code"] for factor in body["factors"]} == {
        "DOMICILE_FOUND",
        "COMPANY",
        "NAME_MATCHES",
        "TERM_61_TO_90_DAYS",
    }
    assert body["rejection_code"] is None
    assert body["delivery_status"] == "PENDING"
    assert body["invoice_amount"] == "10000.00"


async def test_an_unknown_auction_is_404(sut: ServiceUnderTest, client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/risk-assessments/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "No risk assessment exists for auction missing"}


MYPE = "40000000-0000-4000-8000-000000000001"
AUCTION = "20000000-0000-4000-8000-000000000001"


async def test_the_mype_reads_the_assessment_of_its_own_auction(
    sut: ServiceUnderTest, client: httpx.AsyncClient
) -> None:
    await sut.service.assess_auction(**auction_created())

    response = await client.get(f"/api/v1/mype/risk-assessments/{AUCTION}", headers={"X-User-Id": MYPE})

    assert response.status_code == 200
    body = response.json()
    assert body["risk_grade"] == "B"
    assert body["score"] == 60
    assert {factor["code"]: factor["points"] for factor in body["factors"]}["DOMICILE_FOUND"] == 10
    assert all(factor["detail"] for factor in body["factors"])
    assert body["payer_ruc"]
    # Only the decision: the delivery bookkeeping and the inputs Investment sent stay internal.
    assert set(body) == {
        "auction_id",
        "invoice_id",
        "payer_ruc",
        "payer_name",
        "eligible",
        "risk_grade",
        "score",
        "factors",
        "rejection_code",
        "rejection_reason",
        "provisional",
        "assessed_at",
    }


async def test_another_mypes_assessment_reads_as_not_found(sut: ServiceUnderTest, client: httpx.AsyncClient) -> None:
    await sut.service.assess_auction(**auction_created())

    response = await client.get(
        f"/api/v1/mype/risk-assessments/{AUCTION}", headers={"X-User-Id": "40000000-0000-4000-8000-000000000999"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": f"No risk assessment exists for auction {AUCTION}"}


async def test_the_mype_route_needs_the_gateway_header(sut: ServiceUnderTest, client: httpx.AsyncClient) -> None:
    await sut.service.assess_auction(**auction_created())

    response = await client.get(f"/api/v1/mype/risk-assessments/{AUCTION}")

    assert response.status_code == 401


async def test_liveness_answers_without_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "UP"
