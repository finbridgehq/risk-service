"""HTTP adapter that finds and downloads the public registries.

The version of a file is its ``Last-Modified`` header: SUNAT rebuilds the
padrón every night, and comparing headers costs one ``HEAD`` instead of a
400 MB download. The same goes for SUNAT's and OECE's sanction lists, which
sit at fixed URLs. Two sources are different:

* The agents registry is published once a month under a name with the period
  (``…_202609.zip``), so finding it means trying the current month and going
  back until one exists.
* OEFA's register comes from its portal as JSON, with no ``Last-Modified``; its
  version is the portal's own "updated to…" title. If the portal does not
  answer, the older open-data CSV is used instead.
"""
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from registries.application.outbound_services import PublishedVersion, RegistryDownloader, RegistryUnavailableError
from registries.domain.value_objects import RegistrySource
from registries.infrastructure.settings import RegistrySettings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024


class HttpRegistryDownloader(RegistryDownloader):
    """Asks SUNAT, OECE, OEFA and the open-data portal for their files over HTTP."""

    def __init__(self, client: httpx.AsyncClient, settings: RegistrySettings, today: Callable[[], date]) -> None:
        """Initialize the downloader.

        Args:
            client (httpx.AsyncClient): A client that follows redirects and sends
                ``settings.user_agent``.
            settings (RegistrySettings): Where the files are.
            today (Callable[[], date]): Today's date, to name the agents file's period.
        """
        self._client = client
        self._settings = settings
        self._today = today

    async def find_published_version(self, source: RegistrySource) -> PublishedVersion:
        match source:
            case RegistrySource.WITHHOLDING_AGENTS:
                return await self._latest_agents_file()
            case RegistrySource.ENVIRONMENTAL_OFFENDERS:
                return await self._environmental_offenders()
            case _:
                return await self._fixed_file(source, self._fixed_urls()[source])

    def _fixed_urls(self) -> dict[RegistrySource, str]:
        settings = self._settings
        return {
            RegistrySource.TAXPAYERS: settings.taxpayers_url,
            RegistrySource.SHELL_COMPANIES: settings.shell_companies_url,
            RegistrySource.COACTIVE_DEBTORS: settings.coactive_debtors_url,
            RegistrySource.OECE_DISQUALIFICATIONS: settings.oece_disqualifications_url,
            RegistrySource.OECE_FINES: settings.oece_fines_url,
        }

    async def _fixed_file(self, source: RegistrySource, url: str) -> PublishedVersion:
        response = await self._head(url)
        if response.status_code != httpx.codes.OK:
            raise RegistryUnavailableError(f"{url} answered HTTP {response.status_code}")
        return PublishedVersion(source=source, version=self._version_of(response), url=url)

    async def _latest_agents_file(self) -> PublishedVersion:
        for period in self._recent_periods():
            url = self._settings.agents_url_template.format(period=period)
            response = await self._head(url)
            if response.status_code == httpx.codes.OK:
                return PublishedVersion(
                    source=RegistrySource.WITHHOLDING_AGENTS, version=f"{period} {self._version_of(response)}", url=url
                )
        raise RegistryUnavailableError(
            f"No agents registry published in the last {self._settings.agents_months_back} months"
        )

    async def _environmental_offenders(self) -> PublishedVersion:
        source = RegistrySource.ENVIRONMENTAL_OFFENDERS
        try:
            response = await self._client.get(self._settings.environmental_offenders_version_url)
            title = response.json()[0]["fechaActualizacion"] if response.status_code == httpx.codes.OK else None
        except (httpx.HTTPError, ValueError, LookupError, TypeError) as error:
            logger.warning("OEFA's portal did not give its update title (%s); using the open-data CSV", error)
            title = None
        if isinstance(title, str) and title.strip():
            return PublishedVersion(
                source=source, version=f"pifa {title.strip()}", url=self._settings.environmental_offenders_url
            )
        fallback = await self._fixed_file(source, self._settings.environmental_offenders_fallback_url)
        return PublishedVersion(source=source, version=f"csv {fallback.version}", url=fallback.url)

    async def download(self, published: PublishedVersion, directory: Path) -> Path:
        target = directory / self._file_name(published)
        try:
            async with self._client.stream("GET", published.url) as response:
                if response.status_code != httpx.codes.OK:
                    raise RegistryUnavailableError(f"{published.url} answered HTTP {response.status_code}")
                with target.open("wb") as file:
                    async for chunk in response.aiter_bytes(CHUNK_SIZE):
                        file.write(chunk)
        except httpx.HTTPError as error:
            raise RegistryUnavailableError(f"Downloading {published.url} failed: {error}") from error
        logger.info("Downloaded %s (%d bytes)", target.name, target.stat().st_size)
        return target

    @staticmethod
    def _file_name(published: PublishedVersion) -> str:
        if published.source is RegistrySource.ENVIRONMENTAL_OFFENDERS:
            return "ruias.csv" if urlsplit(published.url).path.endswith(".csv") else "ruias.json"
        return unquote(urlsplit(published.url).path.rsplit("/", 1)[-1])

    async def _head(self, url: str) -> httpx.Response:
        try:
            return await self._client.head(url)
        except httpx.HTTPError as error:
            raise RegistryUnavailableError(f"{url} could not be reached: {error}") from error

    def _recent_periods(self) -> list[str]:
        today = self._today()
        year, month = today.year, today.month
        periods = []
        for _ in range(self._settings.agents_months_back + 1):
            periods.append(f"{year:04d}{month:02d}")
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        return periods

    @staticmethod
    def _version_of(response: httpx.Response) -> str:
        return (
            response.headers.get("last-modified")
            or response.headers.get("etag")
            or f"size {response.headers.get('content-length', 'unknown')}"
        )
