"""The OpenAI news screener, against canned Responses API answers: no network, no key.

The ``openai`` 3.x SDK runs on ``httpx2``, not ``httpx``, so the mock transport comes from there.
"""
import json
from typing import Any

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from assessments.application.outbound_services import NewsUnavailableError
from assessments.domain.value_objects import NewsCategory, NewsSeverity, Ruc
from assessments.infrastructure.news import OpenAINewsScreener, normalize_url
from assessments.infrastructure.settings import NewsSettings
from tests.fakes import NOW

CONSULTED = "https://www.larepublica.pe/economia/avianca-peru-liquidacion"


def response_body(findings: list[dict[str, Any]], sources: list[str]) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1792000000,
        "model": "gpt-6-luna",
        "status": "completed",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_1",
                "status": "completed",
                "action": {
                    "type": "search",
                    "query": "Avianca Perú",
                    "sources": [{"type": "url", "url": url} for url in sources],
                },
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps({"findings": findings}), "annotations": []}],
            },
        ],
    }


def finding(url: str, category: str = "INSOLVENCY") -> dict[str, Any]:
    return {
        "category": category,
        "headline": "Avianca Perú entra en liquidación",
        "url": url,
        "published_on": "2024-03-01",
        "summary": "La empresa fue declarada en liquidación.",
    }


async def screen(handler: httpx.MockTransport) -> Any:
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="http://openai.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),
    )
    screener = OpenAINewsScreener(client, NewsSettings(api_key=None), clock=lambda: NOW)
    try:
        return await screener.screen(Ruc("20348858182"), "AVIANCA PERÚ S.A. EN LIQUIDACIÓN")
    finally:
        await client.close()


async def test_sends_one_web_search_request_and_keeps_findings_from_consulted_pages() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        body = response_body(
            [finding(CONSULTED + "/"), finding("https://invented.example/fake", "FRAUD")], sources=[CONSULTED]
        )
        return httpx.Response(200, json=body)

    screening = await screen(httpx.MockTransport(handler))

    [request] = seen
    assert request["model"] == "gpt-6-luna"
    assert request["tools"][0]["type"] == "web_search"
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["max_tool_calls"] == 5
    assert "20348858182" in request["input"]
    [kept] = screening.findings
    assert (kept.category, kept.severity) == (NewsCategory.INSOLVENCY, NewsSeverity.SERIOUS)
    assert screening.sources_consulted == 1
    assert screening.model == "gpt-6-luna"


async def test_an_empty_answer_is_a_clean_screening() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body([], [CONSULTED])))
    screening = await screen(transport)
    assert screening.findings == ()


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_api_errors_are_unavailable(status: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(NewsUnavailableError):
        await screen(transport)


async def test_an_answer_that_is_not_the_schema_is_unavailable() -> None:
    body = response_body([], [CONSULTED])
    body["output"][1]["content"][0]["text"] = '{"findings": [{"category": "FRAUD"'
    with pytest.raises(NewsUnavailableError):
        await screen(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.diario.pe/nota/", "http://diario.pe/nota"),
        ("https://diario.pe/nota?utm_source=x&id=3", "https://diario.pe/nota?id=3"),
        ("https://diario.pe/nota#comentarios", "https://diario.pe/nota"),
    ],
)
def test_the_same_page_compares_equal(a: str, b: str) -> None:
    assert normalize_url(a) == normalize_url(b)


async def test_registry_pages_are_dropped_and_severity_follows_the_category() -> None:
    registry = "https://www.sunat.gob.pe/padronesnotificaciones/listaContrib-mayorDeudaExigible-CC.html"
    trial = "https://elcomercio.pe/politica/juicio-trafico-de-influencias"

    def handler(request: httpx.Request) -> httpx.Response:
        body = response_body(
            [finding(registry, "NON_PAYMENT_LITIGATION"), finding(trial, "CORRUPTION")], sources=[registry, trial]
        )
        return httpx.Response(200, json=body)

    screening = await screen(httpx.MockTransport(handler))
    [kept] = screening.findings
    assert kept.url == trial
    assert (kept.category, kept.severity) == (NewsCategory.CORRUPTION, NewsSeverity.SERIOUS)
