"""Downloading a certificate from Profile's bucket."""

import httpx
import pytest

from sustainability.application.outbound_services import DocumentRejectedError, TemporarilyUnavailableError
from sustainability.domain.value_objects import CertificateDocument, DocumentType
from sustainability.infrastructure.documents import HttpxCertificateDocuments
from tests.green_data import OBJECT_KEY

BASE = "http://minio:9000/vankoo-profile-documents/"
PDF = CertificateDocument(OBJECT_KEY, DocumentType.PDF)


async def fetch(handler: httpx.MockTransport, max_bytes: int = 1024) -> bytes:
    async with httpx.AsyncClient(base_url=BASE, transport=handler) as client:
        return await HttpxCertificateDocuments(client, max_bytes).fetch(PDF)


async def test_downloads_the_key_under_its_own_base_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.7 ok")

    assert await fetch(httpx.MockTransport(handler)) == b"%PDF-1.7 ok"
    assert seen == [BASE + OBJECT_KEY]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404), "No se encontró"),
        (httpx.Response(200, content=b"%PDF-" + b"x" * 2000), "supera el máximo"),
        (httpx.Response(200, content=b"<html>not a pdf</html>"), "no es un PDF"),
    ],
)
async def test_a_file_that_cannot_be_used_is_rejected(response: httpx.Response, message: str) -> None:
    with pytest.raises(DocumentRejectedError, match=message):
        await fetch(httpx.MockTransport(lambda request: response))


async def test_a_storage_that_does_not_answer_is_worth_retrying() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(TemporarilyUnavailableError):
        await fetch(httpx.MockTransport(refuse))
    with pytest.raises(TemporarilyUnavailableError):
        await fetch(httpx.MockTransport(lambda request: httpx.Response(503)))
