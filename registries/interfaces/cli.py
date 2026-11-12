"""Command line of the Registries context: ``python -m registries refresh``.

Refreshing the padrón streams a 1.6 GB file into PostgreSQL (the sanction
lists are small), which keeps a
CPU busy for minutes. It runs as its own process, never inside the API's event
loop: by hand, or launched by the scheduler as a subprocess.
"""
import argparse
import asyncio
import logging
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from registries.application.outbound_services import RegistryUnavailableError
from registries.application.services import RegistryRefreshService
from registries.domain.value_objects import RegistrySource
from registries.infrastructure.bulk import PostgresRegistryWriter
from registries.infrastructure.downloads import HttpRegistryDownloader
from registries.infrastructure.repositories import SqlAlchemyRegistrySnapshotRepository
from registries.infrastructure.settings import RegistrySettings, registry_settings
from shared.infrastructure.database import engine, session_factory

logger = logging.getLogger("registries")

SOURCES = {
    "taxpayers": RegistrySource.TAXPAYERS,
    "agents": RegistrySource.WITHHOLDING_AGENTS,
    "shell-companies": RegistrySource.SHELL_COMPANIES,
    "coactive-debtors": RegistrySource.COACTIVE_DEBTORS,
    "oece-disqualifications": RegistrySource.OECE_DISQUALIFICATIONS,
    "oece-fines": RegistrySource.OECE_FINES,
    "environmental-offenders": RegistrySource.ENVIRONMENTAL_OFFENDERS,
}


async def refresh(sources: list[RegistrySource], settings: RegistrySettings, *, force: bool) -> int:
    """Refresh each registry in turn; one failing does not stop the others.

    Returns:
        int: The process exit code: 0 if every registry is up to date, 1 otherwise.
    """
    exit_code = 0
    timeout = httpx.Timeout(settings.download_timeout, connect=15.0)
    headers = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        downloader = HttpRegistryDownloader(client, settings, lambda: _today(settings))
        for source in sources:
            try:
                with tempfile.TemporaryDirectory(prefix="registry-") as workdir:
                    async with session_factory() as session:
                        service = RegistryRefreshService(
                            SqlAlchemyRegistrySnapshotRepository(session),
                            downloader,
                            PostgresRegistryWriter(session),
                            session,
                        )
                        outcome = await service.refresh_registry(source, Path(workdir), force=force)
                print(
                    f"{source}: {'loaded' if outcome.refreshed else 'up to date'}, "
                    f"{outcome.rows_loaded} rows, {outcome.rows_rejected} rejected, version {outcome.version}"
                )
            except RegistryUnavailableError as error:
                logger.error("%s could not be refreshed: %s", source, error)
                exit_code = 1
            except Exception:
                logger.exception("%s could not be refreshed", source)
                exit_code = 1
    await engine.dispose()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run it."""
    parser = argparse.ArgumentParser(prog="python -m registries", description="Keep SUNAT's registries up to date.")
    commands = parser.add_subparsers(dest="command", required=True)
    refresh_command = commands.add_parser("refresh", help="download and load the registries SUNAT published")
    refresh_command.add_argument(
        "--source", choices=[*SOURCES, "all"], default="all", help="which registry to refresh (default: all)"
    )
    refresh_command.add_argument("--force", action="store_true", help="load even if the version did not change")
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
    sources = list(SOURCES.values()) if arguments.source == "all" else [SOURCES[arguments.source]]
    return asyncio.run(refresh(sources, registry_settings, force=arguments.force))


def _today(settings: RegistrySettings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


if __name__ == "__main__":
    sys.exit(main())
