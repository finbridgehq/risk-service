"""Adapter that downloads certificates from Profile's bucket.

The download itself is the shared kernel's (``shared.infrastructure.documents``);
this adapter adds what a certificate must be: a PDF, JPEG or PNG under its limit.
"""
import httpx

from shared.infrastructure.documents import (
    DocumentMissingError,
    DocumentTooLargeError,
    StorageUnavailableError,
    download_document,
)
from sustainability.application.outbound_services import (
    CertificateDocuments,
    DocumentRejectedError,
    TemporarilyUnavailableError,
)
from sustainability.domain.value_objects import CertificateDocument, DocumentType

# What each type starts with, so a renamed file is not read as what it is not.
MAGIC_NUMBERS = {
    DocumentType.PDF: (b"%PDF-",),
    DocumentType.JPEG: (b"\xff\xd8\xff",),
    DocumentType.PNG: (b"\x89PNG\r\n\x1a\n",),
}


class HttpxCertificateDocuments(CertificateDocuments):
    """Downloads certificates with a process-wide httpx client."""

    def __init__(self, client: httpx.AsyncClient, max_bytes: int) -> None:
        """Initialize the adapter.

        Args:
            client (httpx.AsyncClient): A client whose ``base_url`` is the bucket's.
            max_bytes (int): The largest file accepted.
        """
        self._client = client
        self._max_bytes = max_bytes

    async def fetch(self, document: CertificateDocument) -> bytes:
        try:
            content = await download_document(self._client, document.object_key, self._max_bytes)
        except DocumentMissingError:
            raise DocumentRejectedError("No se encontró el archivo del certificado") from None
        except DocumentTooLargeError:
            raise DocumentRejectedError(
                f"El archivo supera el máximo de {self._max_bytes // (1024 * 1024)} MB"
            ) from None
        except StorageUnavailableError as error:
            raise TemporarilyUnavailableError(str(error)) from error
        if not content.startswith(MAGIC_NUMBERS[document.document_type]):
            raise DocumentRejectedError("El archivo no es un PDF, JPG o PNG válido")
        return content
