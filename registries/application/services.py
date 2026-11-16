"""Application service of the Registries bounded context."""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from registries.application.outbound_services import RegistryDownloader, RegistryWriter
from registries.domain.entities import RegistrySnapshot
from registries.domain.repositories import RegistrySnapshotRepository
from registries.domain.value_objects import RegistrySource
from shared.application.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current time in UTC; the default clock."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshOutcome:
    """What a refresh did.

    Attributes:
        source (RegistrySource): Which registry.
        version (str): The version the local copy holds now.
        refreshed (bool): Whether a new version was loaded; ``False`` when the
            local copy was already up to date.
        rows_loaded (int): Rows in the local copy.
        rows_rejected (int): Rows of the file that could not be read.
    """

    source: RegistrySource
    version: str
    refreshed: bool
    rows_loaded: int
    rows_rejected: int


class RegistryRefreshService:
    """Keeps the local copy of each SUNAT registry on the version SUNAT publishes."""

    def __init__(
        self,
        snapshot_repository: RegistrySnapshotRepository,
        downloader: RegistryDownloader,
        writer: RegistryWriter,
        unit_of_work: UnitOfWork,
        clock: Clock = utc_now,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            snapshot_repository (RegistrySnapshotRepository): The loads made so far.
            downloader (RegistryDownloader): Finds and downloads SUNAT's files.
            writer (RegistryWriter): Replaces the local copy.
            unit_of_work (UnitOfWork): The transaction to commit.
            clock (Clock): The current time, replaceable in tests.
        """
        self._snapshots = snapshot_repository
        self._downloader = downloader
        self._writer = writer
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def refresh_registry(self, source: RegistrySource, workdir: Path, *, force: bool = False) -> RefreshOutcome:
        """Load the published version of a registry unless the local copy already has it.

        The new copy and its snapshot are committed together; until then,
        and if anything fails, readers keep the previous copy.

        Args:
            source (RegistrySource): Which registry to refresh.
            workdir (Path): Where the download can be written; the caller removes it.
            force (bool): Load even if the version did not change.

        Raises:
            RegistryUnavailableError: If SUNAT's file cannot be reached or downloaded.
        """
        published = await self._downloader.find_published_version(source)
        latest = await self._snapshots.find_latest(source)
        if latest is not None and latest.is_version(published.version) and not force:
            logger.info("%s is up to date (%s); nothing to download", source, published.version)
            return RefreshOutcome(
                source=source,
                version=latest.version,
                refreshed=False,
                rows_loaded=latest.rows_loaded,
                rows_rejected=latest.rows_rejected,
            )

        logger.info("Downloading %s version %s from %s", source, published.version, published.url)
        file = await self._downloader.download(published, workdir)
        logger.info("Loading %s", file.name)
        result = await self._writer.replace(source, file)
        snapshot = RegistrySnapshot(source, published.version, self._clock(), result.rows_loaded, result.rows_rejected)
        await self._snapshots.save(snapshot)
        await self._unit_of_work.commit()
        logger.info(
            "%s loaded: %d rows, %d rejected (version %s)",
            source,
            result.rows_loaded,
            result.rows_rejected,
            published.version,
        )
        return RefreshOutcome(
            source=source,
            version=published.version,
            refreshed=True,
            rows_loaded=result.rows_loaded,
            rows_rejected=result.rows_rejected,
        )
