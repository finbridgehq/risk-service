"""Adapter that downloads fichas RUC from Profile's bucket.

The download itself is the shared kernel's (``shared.infrastructure.documents``);
this adapter adds what a ficha must be: a PDF under its limit.
"""
import httpx

from shared.infrastructure.documents import (
    DocumentMissingError,
    DocumentTooLargeError,
    StorageUnavailableError,
    download_document,
)
from verification.application.outbound_services import (
    DocumentRejectedError,
    RucDocuments,
    TemporarilyUnavailableError,
)
from verification.domain.value_objects import RucDocument

PDF_MAGIC = b"%PDF-"


class HttpxRucDocuments(RucDocuments):
    """Downloads fichas RUC with a process-wide httpx client."""

    def __init__(self, client: httpx.AsyncClient, max_bytes: int) -> None:
        """Initialize the adapter.

        Args:
            client (httpx.AsyncClient): A client whose ``base_url`` is the bucket's.
            max_bytes (int): The largest file accepted.
        """
        self._client = client
        self._max_bytes = max_bytes

    async def fetch(self, document: RucDocument) -> bytes:
        try:
            content = await download_document(self._client, document.object_key, self._max_bytes)
        except DocumentMissingError:
            raise DocumentRejectedError("No se encontró el archivo de la ficha RUC") from None
        except DocumentTooLargeError:
            raise DocumentRejectedError(
                f"El archivo supera el máximo de {self._max_bytes // (1024 * 1024)} MB"
            ) from None
        except StorageUnavailableError as error:
            raise TemporarilyUnavailableError(str(error)) from error
        if not content.startswith(PDF_MAGIC):
            raise DocumentRejectedError("La ficha RUC no es un PDF válido")
        return content
