"""Reading the sanction lists: SUNAT's XLSX, OECE's CSV and OEFA's JSON or CSV."""
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from registries.infrastructure.parsers import (
    normalize_ruc,
    read_coactive_debtors,
    read_environmental_offenders,
    read_oece_sanctions,
    read_shell_companies,
)
from shared.domain.exceptions import DomainError


def xlsx(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def test_reads_the_shell_companies_list_with_numeric_rucs(tmp_path: Path) -> None:
    file = xlsx(
        tmp_path / "ssco.xlsx",
        [
            ["RUC", "Razón social", "Domicilio", "Resolución", "Emisión", "Firme", "Doc", "Representante",
             "Publicación"],
            [20123456789, "EMPRESA DE PAPEL SAC", "AV. X", "RI N.º 1", datetime(2026, 8, 26), datetime(2026, 9, 10),
             "123", "PERSONA", datetime(2026, 9, 30)],
            ["no-ruc", "MALA", "", "", None, None, "", "", None],
        ],
    )
    records = list(read_shell_companies(file))
    first = records[0]
    assert first is not None
    assert (first.ruc, first.name, first.resolution) == ("20123456789", "EMPRESA DE PAPEL SAC", "RI N.º 1")
    assert (first.resolution_date, first.final_date, first.published_on) == (
        date(2026, 8, 26),
        date(2026, 9, 10),
        date(2026, 9, 30),
    )
    assert records[1] is None


def test_reads_the_coactive_debt_list(tmp_path: Path) -> None:
    file = xlsx(
        tmp_path / "deuda.xlsx",
        [
            ["N°", "RUC DEL DEUDOR", "NOMBRE", "COMERCIAL", "DEPENDENCIA", "MONTO", "REPRESENTANTES"],
            ["1", "20348858182", "AVIANCA PERÚ S.A.", "-", "I.Lima", 1346447643, "2"],
        ],
    )
    [record] = list(read_coactive_debtors(file))
    assert record is not None
    assert record.ruc == "20348858182"
    assert record.debt_amount == Decimal("1346447643.00")


def test_reads_an_oece_csv_in_cp1252_with_compact_dates(tmp_path: Path) -> None:
    file = tmp_path / "sancionados_multa.csv"
    file.write_bytes(
        (
            "FECHA_CORTE|RUC|NOMBRE_RAZONODENOMINACIONSOCIAL|FECHA_INICIO|FECHA_FIN|NUMERO_RESOLUCION|"
            "ID_MOTIVO_INFRACCION|DE_MOTIVO_INFRACCION|MONTO\r\n"
            "20261003|20100994128|CONSTRUCTORA – DOS DE MAYO|20230103||4291-2022-TCE-S4|237,|b) Incumplir|23000.00\r\n"
            "20261003|2029124996 |CORTO|20230103|20230503|1-2023|1,|x| 100\r\n"
        ).encode("cp1252")
    )
    first, second = list(read_oece_sanctions(file))
    assert first is not None
    assert (first.starts_on, first.ends_on, first.amount) == (date(2023, 1, 3), None, Decimal("23000.00"))
    assert first.resolution == "4291-2022-TCE-S4"
    assert second is None


def test_reads_oefa_from_the_portal_json(tmp_path: Path) -> None:
    file = tmp_path / "ruias.json"
    file.write_text(
        json.dumps(
            [
                {"administrado": "MINERA S.A.", "ruc": "20109989992", "subsector": "Minería", "uit": "71480.78",
                 "infracciones": "78", "codigo": "ADM1"},
                {"administrado": "SIN RUC", "ruc": "-", "subsector": "", "uit": "0", "infracciones": "1"},
            ]
        )
    )
    first, second = list(read_environmental_offenders(file))
    assert first is not None
    assert (first.ruc, first.infractions, first.fine_uit) == ("20109989992", 78, Decimal("71480.78"))
    assert second is None


def test_reads_oefa_from_the_open_data_csv_grouping_offences_by_ruc(tmp_path: Path) -> None:
    file = tmp_path / "ruias.csv"
    file.write_text(
        '"";TIPO_DOC;ID_DOC_ADMINISTRADO;NOMBRE_ADMINISTRADO;SUBSECTOR_ECONOMICO;CANTIDAD_MULTA\r\n'
        '"1";"R.U.C.";"20109989992";"MINERA S.A.";"Minería";"10,5"\r\n'
        '"2";"R.U.C.";"20109989992";"MINERA S.A.";"Minería";"-"\r\n'
        '"3";"D.N.I.";"12345678";"PERSONA";"Pesca";"1"\r\n',
        encoding="utf-8",
    )
    records = list(read_environmental_offenders(file))
    offenders = [r for r in records if r]
    assert len(offenders) == 1
    assert (offenders[0].infractions, offenders[0].fine_uit) == (2, Decimal("10.50"))
    assert records.count(None) == 1


@pytest.mark.parametrize(("raw", "ruc"), [(20123456789, "20123456789"), (20123456789.0, "20123456789"),
                                         (" 20123456789 ", "20123456789")])
def test_rucs_are_normalized(raw: object, ruc: str) -> None:
    assert normalize_ruc(raw) == ruc


@pytest.mark.parametrize("raw", ["X0546340059", "2029124996", None, ""])
def test_malformed_rucs_are_refused(raw: object) -> None:
    with pytest.raises(DomainError):
        normalize_ruc(raw)
