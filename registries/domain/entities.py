"""Aggregates of the Registries bounded context."""
from datetime import datetime

from registries.domain.value_objects import RegistrySource
from shared.domain.entities import AggregateRoot
from shared.domain.exceptions import DomainError


class RegistrySnapshot(AggregateRoot):
    """One successful load of a SUNAT registry into this service.

    The latest snapshot of a source says which published version the local
    copy holds, so a refresh can skip a download when SUNAT has published
    nothing new, and the assessments know whether the registry is there at all.

    Attributes:
        id (int | None): Identity assigned when the snapshot is first saved.
        source (RegistrySource): Which registry was loaded.
        version (str): The published version, e.g. the file's ``Last-Modified``.
        loaded_at (datetime): When the load finished, in UTC.
        rows_loaded (int): Rows now in the local copy.
        rows_rejected (int): Rows of the file that could not be read.
    """

    def __init__(
        self,
        source: RegistrySource,
        version: str,
        loaded_at: datetime,
        rows_loaded: int,
        rows_rejected: int,
        id: int | None = None,
    ) -> None:
        """Initialize a snapshot.

        Raises:
            DomainError: If the version is blank, a count is negative, or
                ``loaded_at`` has no time zone.
        """
        super().__init__()
        if not version.strip():
            raise DomainError("A registry snapshot must say which version it loaded")
        if rows_loaded < 0 or rows_rejected < 0:
            raise DomainError("Row counts cannot be negative")
        if loaded_at.tzinfo is None:
            raise DomainError("Load time must carry a time zone")
        self._id = id
        self._source = source
        self._version = version.strip()
        self._loaded_at = loaded_at
        self._rows_loaded = rows_loaded
        self._rows_rejected = rows_rejected

    @property
    def id(self) -> int | None:
        """Identity assigned by the first save; ``None`` before it."""
        return self._id

    @property
    def source(self) -> RegistrySource:
        """Which registry was loaded."""
        return self._source

    @property
    def version(self) -> str:
        """The published version the local copy holds."""
        return self._version

    @property
    def loaded_at(self) -> datetime:
        """When the load finished."""
        return self._loaded_at

    @property
    def rows_loaded(self) -> int:
        """Rows now in the local copy."""
        return self._rows_loaded

    @property
    def rows_rejected(self) -> int:
        """Rows of the file that could not be read."""
        return self._rows_rejected

    def is_version(self, version: str) -> bool:
        """Tell whether this snapshot holds the given published version."""
        return self._version == version.strip()
