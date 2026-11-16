"""Refreshing a registry: skip when nothing changed, load and record otherwise."""
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from registries.application.outbound_services import (
    LoadResult,
    PublishedVersion,
    RegistryDownloader,
    RegistryUnavailableError,
    RegistryWriter,
)
from registries.application.services import RegistryRefreshService
from registries.domain.entities import RegistrySnapshot
from registries.domain.repositories import RegistrySnapshotRepository
from registries.domain.value_objects import RegistrySource
from registries.infrastructure.downloads import HttpRegistryDownloader
from registries.infrastructure.settings import RegistrySettings
from registries.interfaces.scheduler import RegistryRefreshScheduler
from tests.fakes import FakeUnitOfWork

TODAY = date(2026, 10, 14)


def downloader_on(client: httpx.AsyncClient) -> HttpRegistryDownloader:
    return HttpRegistryDownloader(client, RegistrySettings(), lambda: TODAY)

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
VERSION = "Wed, 14 Oct 2026 07:39:02 GMT"


class InMemorySnapshots(RegistrySnapshotRepository):
    def __init__(self) -> None:
        self.saved: list[RegistrySnapshot] = []

    async def save(self, snapshot: RegistrySnapshot) -> RegistrySnapshot:
        self.saved.append(snapshot)
        return snapshot

    async def find_latest(self, source: RegistrySource) -> RegistrySnapshot | None:
        return next((s for s in reversed(self.saved) if s.source is source), None)


class FakeDownloader(RegistryDownloader):
    def __init__(self, version: str = VERSION) -> None:
        self.version = version
        self.downloads = 0

    async def find_published_version(self, source: RegistrySource) -> PublishedVersion:
        return PublishedVersion(source=source, version=self.version, url="https://sunat.example/padron.zip")

    async def download(self, published: PublishedVersion, directory: Path) -> Path:
        self.downloads += 1
        return directory / "padron.zip"


class FakeWriter(RegistryWriter):
    def __init__(self) -> None:
        self.loads = 0

    async def replace(self, source: RegistrySource, file: Path) -> LoadResult:
        self.loads += 1
        return LoadResult(rows_loaded=18_000_000, rows_rejected=12)


def service(snapshots: InMemorySnapshots, downloader: FakeDownloader, writer: FakeWriter) -> RegistryRefreshService:
    return RegistryRefreshService(snapshots, downloader, writer, FakeUnitOfWork(), lambda: NOW)


async def test_loads_a_new_version_and_records_the_snapshot(tmp_path: Path) -> None:
    snapshots, downloader, writer = InMemorySnapshots(), FakeDownloader(), FakeWriter()

    outcome = await service(snapshots, downloader, writer).refresh_registry(RegistrySource.TAXPAYERS, tmp_path)

    assert outcome.refreshed is True
    assert (outcome.rows_loaded, outcome.rows_rejected) == (18_000_000, 12)
    [snapshot] = snapshots.saved
    assert snapshot.version == VERSION and snapshot.loaded_at == NOW


async def test_skips_the_download_when_the_version_did_not_change(tmp_path: Path) -> None:
    snapshots, downloader, writer = InMemorySnapshots(), FakeDownloader(), FakeWriter()
    await service(snapshots, downloader, writer).refresh_registry(RegistrySource.TAXPAYERS, tmp_path)

    outcome = await service(snapshots, downloader, writer).refresh_registry(RegistrySource.TAXPAYERS, tmp_path)

    assert outcome.refreshed is False
    assert downloader.downloads == 1 and writer.loads == 1


async def test_force_loads_the_same_version_again(tmp_path: Path) -> None:
    snapshots, downloader, writer = InMemorySnapshots(), FakeDownloader(), FakeWriter()
    await service(snapshots, downloader, writer).refresh_registry(RegistrySource.TAXPAYERS, tmp_path)

    await service(snapshots, downloader, writer).refresh_registry(RegistrySource.TAXPAYERS, tmp_path, force=True)

    assert writer.loads == 2


async def test_the_downloader_reads_the_version_from_last_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"Last-Modified": VERSION})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        published = await downloader_on(client).find_published_version(RegistrySource.TAXPAYERS)
    assert published.version == VERSION


async def test_the_downloader_goes_back_to_the_latest_published_agents_month() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path.rsplit("_", 1)[-1])
        found = request.url.path.endswith("202609.zip")
        return httpx.Response(200 if found else 404, headers={"Last-Modified": VERSION})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        published = await downloader_on(client).find_published_version(RegistrySource.WITHHOLDING_AGENTS)
    assert asked == ["202610.zip", "202609.zip"]
    assert published.version.startswith("202609 ")


async def test_the_downloader_reports_an_unreachable_registry() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        with pytest.raises(RegistryUnavailableError):
            await downloader_on(client).find_published_version(RegistrySource.TAXPAYERS)


def test_the_scheduler_waits_until_the_next_refresh_hour() -> None:
    from zoneinfo import ZoneInfo

    scheduler = RegistryRefreshScheduler(RegistrySettings(refresh_hour=4))
    lima = ZoneInfo("America/Lima")
    assert scheduler.seconds_until_next_run(datetime(2026, 10, 14, 3, 30, tzinfo=lima)) == 30 * 60
    assert scheduler.seconds_until_next_run(datetime(2026, 10, 14, 4, 0, tzinfo=lima)) == 24 * 3600


async def test_oefa_is_versioned_by_its_portal_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("obtenerTituloActualizacionRuias.do")
        return httpx.Response(200, json=[{"fechaActualizacion": "Actualizado a Noviembre del 2025"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        published = await downloader_on(client).find_published_version(RegistrySource.ENVIRONMENTAL_OFFENDERS)
    assert published.version == "pifa Actualizado a Noviembre del 2025"
    assert "mostrarDetalleRasmaResumen" in published.url


async def test_oefa_falls_back_to_the_open_data_csv_when_the_portal_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oefa" in request.url.host:
            return httpx.Response(500)
        return httpx.Response(200, headers={"Last-Modified": VERSION})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        published = await downloader_on(client).find_published_version(RegistrySource.ENVIRONMENTAL_OFFENDERS)
    assert published.version == f"csv {VERSION}"
    assert published.url.endswith(".csv")


@pytest.mark.parametrize(
    "source",
    [RegistrySource.SHELL_COMPANIES, RegistrySource.COACTIVE_DEBTORS, RegistrySource.OECE_DISQUALIFICATIONS,
     RegistrySource.OECE_FINES],
)
async def test_fixed_sanction_files_are_versioned_by_last_modified(source: RegistrySource) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"Last-Modified": VERSION}))
    ) as client:
        published = await downloader_on(client).find_published_version(source)
    assert published.version == VERSION
