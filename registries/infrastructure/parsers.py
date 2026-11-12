"""Readers of the files SUNAT publishes.

The padrón reducido del RUC is a ZIP with one text file of about 1.6 GB:
latin-1, ``|``-separated with a trailing ``|``, 15 columns, ``-`` for an empty
value, and no quoting. Some names contain a ``|`` themselves, so a line can
have more fields than columns; the RUC is always first and the last 13 columns
are fixed, so whatever lies between them is the name.

The registry of IGV agents is a ZIP with one UTF-8 CSV (quoted, since names
contain commas) of a few thousand rows, one per RUC and agent role.

The sanction lists are small: SUNAT publishes two as XLSX (where a RUC can be a
number or a text cell), OECE two as ``|``-separated cp1252 CSV with
``YYYYMMDD`` dates, and OEFA its register as JSON (with an older CSV, ``;``
separated and with decimal commas, as fallback).

Every reader streams or reads row by row. A row that cannot be read yields
``None``, so the caller can count it as rejected.
"""
import csv
import io
import json
import unicodedata
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from registries.domain.value_objects import (
    AgentRecord,
    AgentType,
    CoactiveDebtorRecord,
    EnvironmentalOffenderRecord,
    OeceSanctionRecord,
    ShellCompanyRecord,
    TaxpayerRecord,
)
from shared.domain.exceptions import DomainError

TAXPAYER_COLUMNS = 15
FIXED_TRAILING_COLUMNS = 13
EMPTY = "-"
MAX_STATUS_LENGTH = 40


def read_taxpayers(file: Path) -> Iterator[TaxpayerRecord | None]:
    """Yield every row of a padrón reducido ZIP, skipping its header.

    Args:
        file (Path): The downloaded ``padron_reducido_ruc.zip``.

    Yields:
        TaxpayerRecord | None: One record per line, or ``None`` for a line that
        cannot be read.
    """
    with zipfile.ZipFile(file) as archive, archive.open(_single_member(archive, ".txt")) as raw:
        text = io.TextIOWrapper(raw, encoding="latin-1", newline=None)
        for number, line in enumerate(text):
            if number == 0 and line.startswith("RUC|"):
                continue
            yield parse_taxpayer_line(line)


def parse_taxpayer_line(line: str) -> TaxpayerRecord | None:
    """Read one line of the padrón reducido.

    Args:
        line (str): The line, with or without its line break.

    Returns:
        TaxpayerRecord | None: The record, or ``None`` if the line has too few
        fields or no valid RUC.
    """
    fields = line.rstrip("\r\n").split("|")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) < TAXPAYER_COLUMNS:
        return None
    ruc = fields[0].strip()
    name = "|".join(fields[1 : len(fields) - FIXED_TRAILING_COLUMNS]).strip()
    status, condition, ubigeo = (value.strip() for value in fields[-FIXED_TRAILING_COLUMNS:][:3])
    try:
        return TaxpayerRecord(
            ruc=ruc,
            name="" if name == EMPTY else name,
            status=status[:MAX_STATUS_LENGTH],
            domicile_condition=condition[:MAX_STATUS_LENGTH],
            ubigeo=ubigeo if ubigeo.isdigit() and len(ubigeo) == 6 else None,
        )
    except DomainError:
        return None


def read_agents(file: Path) -> Iterator[AgentRecord | None]:
    """Yield every row of the open-data registry of IGV agents.

    Args:
        file (Path): The downloaded ``padron_agentes_retencion_percepcion_igv_YYYYMM.zip``.

    Yields:
        AgentRecord | None: One record per row, or ``None`` for a row that
        cannot be read.
    """
    with zipfile.ZipFile(file) as archive, archive.open(_single_member(archive, ".csv")) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text):
            yield parse_agent_row(row)


def parse_agent_row(row: dict[str, str | None]) -> AgentRecord | None:
    """Read one row of the agents CSV (``fecha_corte,RUC,nombre_o_razon_social,fecha_alta,…``).

    Returns:
        AgentRecord | None: The record, or ``None`` if the RUC or the role cannot be read.
    """
    agent_type = agent_type_from_label(row.get("tipo_agente") or "")
    if agent_type is None:
        return None
    resolution = (row.get("numero_resolucion") or "").strip() or None
    try:
        return AgentRecord(
            ruc=(row.get("RUC") or "").strip(),
            agent_type=agent_type,
            since=_parse_date(row.get("fecha_alta") or ""),
            resolution=resolution[:120] if resolution else None,
        )
    except DomainError:
        return None


def agent_type_from_label(label: str) -> AgentType | None:
    """Map SUNAT's wording (``agente de retención del IGV``…) to an agent role."""
    normalized = _without_accents(label).lower()
    if "retencion" in normalized:
        return AgentType.WITHHOLDING
    if "hidrocarburo" in normalized:
        return AgentType.PERCEPTION_FUEL
    if "percepcion" in normalized:
        return AgentType.PERCEPTION_DOMESTIC_SALES
    return None


def read_shell_companies(file: Path) -> Iterator[ShellCompanyRecord | None]:
    """Yield every row of SUNAT's list of taxpayers without operating capacity (SSCO).

    Columns: RUC, name, fiscal address, resolution, issue date, final date,
    legal representative (two columns, not kept: personal data), publication date.
    """
    for row in _xlsx_rows(file):
        try:
            yield ShellCompanyRecord(
                ruc=normalize_ruc(row[0]),
                name=_text(row[1]) or "",
                resolution=_text(row[3]),
                resolution_date=_cell_date(row[4]),
                final_date=_cell_date(row[5]),
                published_on=_cell_date(row[8]) if len(row) > 8 else None,
            )
        except (DomainError, IndexError):
            yield None


def read_coactive_debtors(file: Path) -> Iterator[CoactiveDebtorRecord | None]:
    """Yield every row of SUNAT's list of the largest debts in coactive collection.

    Columns: N°, RUC, name, trade name, SUNAT office, debt in soles, number of
    legal representatives.
    """
    for row in _xlsx_rows(file):
        try:
            yield CoactiveDebtorRecord(
                ruc=normalize_ruc(row[1]), name=_text(row[2]) or "", debt_amount=_decimal(row[5])
            )
        except (DomainError, IndexError):
            yield None


def read_oece_sanctions(file: Path) -> Iterator[OeceSanctionRecord | None]:
    """Yield every row of an OECE sanctions CSV (disqualifications or fines).

    ``FECHA_CORTE|RUC|NOMBRE…|FECHA_INICIO|FECHA_FIN|NUMERO_RESOLUCION|ID_MOTIVO…|DE_MOTIVO…``,
    plus ``MONTO`` in the fines file. cp1252, dates as ``YYYYMMDD``.
    """
    with file.open(encoding="cp1252", errors="replace", newline="") as text:
        for row in csv.DictReader(text, delimiter="|", quoting=csv.QUOTE_NONE):
            try:
                resolution = (row.get("NUMERO_RESOLUCION") or "").strip()
                if not resolution:
                    yield None
                    continue
                yield OeceSanctionRecord(
                    ruc=normalize_ruc(row.get("RUC")),
                    resolution=resolution[:120],
                    starts_on=_compact_date(row.get("FECHA_INICIO")),
                    ends_on=_compact_date(row.get("FECHA_FIN")),
                    reason=_text(row.get("DE_MOTIVO_INFRACCION")),
                    amount=_decimal(row.get("MONTO")),
                )
            except DomainError:
                yield None


def read_environmental_offenders(file: Path) -> Iterator[EnvironmentalOffenderRecord | None]:
    """Yield every offender of OEFA's register: its portal's JSON, or the open-data CSV.

    The JSON is a list of ``{administrado, ruc, subsector, uit, infracciones, codigo}``.
    The CSV has one row per offence, so it is grouped by RUC here.
    """
    if file.suffix.lower() == ".json":
        for item in json.loads(file.read_text(encoding="utf-8")):
            try:
                yield EnvironmentalOffenderRecord(
                    ruc=normalize_ruc(item.get("ruc")),
                    name=_text(item.get("administrado")) or "",
                    subsector=_text(item.get("subsector")),
                    infractions=int(item.get("infracciones") or 0),
                    fine_uit=_decimal(item.get("uit")),
                )
            except (DomainError, ValueError, AttributeError):
                yield None
        return

    offenders: dict[str, EnvironmentalOffenderRecord] = {}
    rejected = 0
    with file.open(encoding="utf-8-sig", newline="") as text:
        for row in csv.DictReader(text, delimiter=";"):
            try:
                ruc = normalize_ruc(row.get("ID_DOC_ADMINISTRADO"))
            except DomainError:
                rejected += 1
                continue
            known = offenders.get(ruc)
            fine = _decimal((row.get("CANTIDAD_MULTA") or "").replace(",", ".")) or Decimal(0)
            offenders[ruc] = EnvironmentalOffenderRecord(
                ruc=ruc,
                name=_text(row.get("NOMBRE_ADMINISTRADO")) or "",
                subsector=_text(row.get("SUBSECTOR_ECONOMICO")),
                infractions=(known.infractions if known else 0) + 1,
                fine_uit=((known.fine_uit or Decimal(0)) if known else Decimal(0)) + fine,
            )
    yield from offenders.values()
    for _ in range(rejected):
        yield None


def normalize_ruc(value: Any) -> str:
    """Write a RUC as eleven digits, however the file stored it (number, text, with spaces).

    Raises:
        DomainError: If what is left is not exactly eleven digits.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value if value is not None else "").strip().replace(" ", "")
    if len(text) != 11 or not text.isdigit():
        raise DomainError(f"'{text}' is not a RUC")
    return text


def _xlsx_rows(file: Path) -> Iterator[tuple[Any, ...]]:
    workbook = load_workbook(file, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = sheet.iter_rows(values_only=True)
        next(rows, None)
        for row in rows:
            if any(cell not in (None, "") for cell in row):
                yield row
    finally:
        workbook.close()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return None if text in ("", EMPTY) else text


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _cell_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _parse_date(str(value)) if value else None


def _compact_date(value: str | None) -> date | None:
    value = (value or "").strip()
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _without_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _single_member(archive: zipfile.ZipFile, extension: str) -> str:
    names = [name for name in archive.namelist() if name.lower().endswith(extension)]
    if len(names) != 1:
        raise ValueError(f"Expected one {extension} file in the archive, found {names}")
    return names[0]
