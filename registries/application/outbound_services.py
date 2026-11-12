"""Outbound ports of the Registries application layer.

Refreshing a registry needs two things the domain cannot express: asking SUNAT
which version it publishes and downloading it, and replacing the local copy
with the downloaded file. Both are ports, so the refresh use case can be tested
without the network or the database.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from registries.domain.value_objects import RegistrySource


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishedVersion:
    """The version of a registry SUNAT publishes right now.

    Attributes:
        source (RegistrySource): Which registry.
        version (str): What identifies it, e.g. the file's ``Last-Modified``.
        url (str): Where to download it.
    """

    source: RegistrySource
    version: str
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadResult:
    """How a downloaded file went into the local copy.

    Attributes:
        rows_loaded (int): Rows now in the local copy.
        rows_rejected (int): Rows of the file that could not be read.
    """

    rows_loaded: int
    rows_rejected: int


class RegistryUnavailableError(Exception):
    """SUNAT's registry could not be reached or downloaded."""


class RegistryDownloader(ABC):
    """Finds and downloads the registries SUNAT publishes."""

    @abstractmethod
    async def find_published_version(self, source: RegistrySource) -> PublishedVersion:
        """Ask which version of a registry is published, without downloading it.

        Raises:
            RegistryUnavailableError: If the source cannot be reached.
        """

    @abstractmethod
    async def download(self, published: PublishedVersion, directory: Path) -> Path:
        """Download a published registry into a directory.

        Returns:
            Path: The downloaded file.

        Raises:
            RegistryUnavailableError: If the download fails.
        """


class RegistryWriter(ABC):
    """Replaces the local copy of a registry with a downloaded file."""

    @abstractmethod
    async def replace(self, source: RegistrySource, file: Path) -> LoadResult:
        """Load the file and swap it in for the current copy, in the caller's transaction.

        Readers keep seeing the previous copy until the transaction commits;
        if anything fails, the previous copy stays as it was.
        """
