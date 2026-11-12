"""Outbound ports of the Sustainability application layer.

:class:`CertificateDocuments` fetches the file the MYPE uploaded,
:class:`CertificateReader` extracts its facts and
:class:`GreenCertificationPublisher` tells Profile the decision. Each says
which failures are worth retrying and which are final: a storage or model that
does not answer is retried, a file that cannot be read is decided on as it is.
"""
from abc import ABC, abstractmethod

from sustainability.domain.entities import GreenCertification
from sustainability.domain.value_objects import CertificateDocument, CertificateExtraction


class TemporarilyUnavailableError(Exception):
    """A dependency did not answer; the same submission is tried again later."""


class DocumentRejectedError(Exception):
    """The file cannot be used (missing, too large, of another type); the decision is NOT_GREEN."""


class CertificateUnreadableError(Exception):
    """The reader could not make sense of the file; the decision is NOT_GREEN."""


class CertificateDocuments(ABC):
    """Where the certificates the MYPEs upload are stored."""

    @abstractmethod
    async def fetch(self, document: CertificateDocument) -> bytes:
        """Download a certificate.

        Returns:
            bytes: The file.

        Raises:
            DocumentRejectedError: If the file is missing, too large or not of its type.
            TemporarilyUnavailableError: If the storage did not answer.
        """


class CertificateReader(ABC):
    """Reads the facts printed on a certificate; it never decides."""

    @property
    @abstractmethod
    def name(self) -> str:
        """What reads, e.g. the model, kept with each decision."""

    @property
    @abstractmethod
    def active(self) -> bool:
        """Whether it can read at all; without it no decision is made."""

    @abstractmethod
    async def read(self, document: CertificateDocument, content: bytes) -> CertificateExtraction:
        """Extract the facts of a certificate.

        Args:
            document (CertificateDocument): The file's key and type.
            content (bytes): The file.

        Returns:
            CertificateExtraction: What is printed on it.

        Raises:
            CertificateUnreadableError: If its answer is unusable.
            TemporarilyUnavailableError: If the reader did not answer.
        """


class GreenCertificationPublisher(ABC):
    """Tells the Profile context about a decision, in the same transaction that stores it."""

    @abstractmethod
    async def publish_decided(self, certification: GreenCertification) -> None:
        """Queue the ``GreenCertificationIssued`` integration event; the caller commits."""
