"""Outbound ports of the Verification application layer.

:class:`RucDocuments` fetches the ficha RUC the MYPE uploaded,
:class:`RucDocumentInspector` checks its signature and reads its text, and
:class:`CompanyVerificationPublisher` tells Profile the decision. Each says
which failures are worth retrying and which are final: a storage that does not
answer is retried, a file that cannot be used is decided on as it is.
"""
from abc import ABC, abstractmethod

from verification.domain.entities import CompanyVerification
from verification.domain.value_objects import RucDocument, RucDocumentInspection


class TemporarilyUnavailableError(Exception):
    """A dependency did not answer, or the registries are not loaded; the same request is tried again later."""


class DocumentRejectedError(Exception):
    """The file cannot be used (missing, too large, not a PDF); the ficha is decided on as unsigned."""


class RucDocuments(ABC):
    """Where the fichas RUC the MYPEs upload are stored."""

    @abstractmethod
    async def fetch(self, document: RucDocument) -> bytes:
        """Download a ficha RUC.

        Returns:
            bytes: The file.

        Raises:
            DocumentRejectedError: If the file is missing, too large or not a PDF.
            TemporarilyUnavailableError: If the storage did not answer.
        """


class RucDocumentInspector(ABC):
    """Checks a ficha RUC's digital signature and reads what it prints; it never decides."""

    @abstractmethod
    def inspect(self, content: bytes) -> RucDocumentInspection:
        """Check whose signature covers the file, and read its facts.

        Synchronous and CPU-bound: the caller runs it in a thread.

        Args:
            content (bytes): The PDF.

        Returns:
            RucDocumentInspection: The signature's authority (or why there is
            none) and the facts its text gives. Never raises for a bad file.
        """


class CompanyVerificationPublisher(ABC):
    """Tells the Profile context about a decision, in the same transaction that stores it."""

    @abstractmethod
    async def publish_decided(self, verification: CompanyVerification) -> None:
        """Queue the ``CompanyVerificationIssued`` integration event; the caller commits."""
