"""Reading SUNAT's files: the padrón's quirks and the agents CSV."""
import zipfile
from datetime import date
from pathlib import Path

from registries.domain.value_objects import AgentType
from registries.infrastructure.parsers import (
    agent_type_from_label,
    parse_taxpayer_line,
    read_agents,
    read_taxpayers,
)

HEADER = (
    "RUC|NOMBRE O RAZÓN SOCIAL|ESTADO DEL CONTRIBUYENTE|CONDICIÓN DE DOMICILIO|UBIGEO|TIPO DE VÍA|NOMBRE DE VÍA|"
    "CÓDIGO DE ZONA|TIPO DE ZONA|NÚMERO|INTERIOR|LOTE|DEPARTAMENTO|MANZANA|KILÓMETRO|\n"
)
ADDRESS = "|AV.|JAVIER PRADO|URB.|SAN ISIDRO|123|-|-|-|-|-|"


def test_a_normal_line() -> None:
    record = parse_taxpayer_line("20123456789|PAGADOR S.A.C.|ACTIVO|HABIDO|150131" + ADDRESS + "\n")
    assert record is not None
    assert (record.ruc, record.name, record.status, record.domicile_condition, record.ubigeo) == (
        "20123456789",
        "PAGADOR S.A.C.",
        "ACTIVO",
        "HABIDO",
        "150131",
    )


def test_a_name_with_a_pipe_is_rebuilt() -> None:
    record = parse_taxpayer_line("20123456789|ALFA | OMEGA S.A.|BAJA DE OFICIO|NO HABIDO|-" + ADDRESS)
    assert record is not None
    assert record.name == "ALFA | OMEGA S.A."
    assert record.status == "BAJA DE OFICIO"
    assert record.domicile_condition == "NO HABIDO"
    assert record.ubigeo is None


def test_unreadable_lines_are_none() -> None:
    assert parse_taxpayer_line("20123456789|SOLO|TRES") is None
    assert parse_taxpayer_line("ABC|PAGADOR|ACTIVO|HABIDO|150131" + ADDRESS) is None
    assert parse_taxpayer_line("") is None


def test_reads_a_latin1_zip_skipping_the_header(tmp_path: Path) -> None:
    lines = HEADER + "20123456789|PEÑA & ASOCIADOS S.R.L.|ACTIVO|HABIDO|150131" + ADDRESS + "\n" + "basura\n"
    archive = tmp_path / "padron_reducido_ruc.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("padron_reducido_ruc.txt", lines.encode("latin-1"))

    records = list(read_taxpayers(archive))

    assert len(records) == 2
    assert records[0] is not None and records[0].name == "PEÑA & ASOCIADOS S.R.L."
    assert records[1] is None


def test_reads_the_agents_csv(tmp_path: Path) -> None:
    csv = (
        "fecha_corte,RUC,nombre_o_razon_social,fecha_alta,numero_resolucion,tipo_agente\r\n"
        '2026-09-30,20100047218,"BANCO, DE CREDITO",2002-06-01,R.S. 037-2002,agente de retención del IGV\r\n'
        "2026-09-30,20100047218,BANCO DE CREDITO,2010-01-01,-,agente de percepción del IGV por venta interna\r\n"
        "2026-09-30,20100128056,SHELL,2010-01-01,-,agente de percepción del IGV por hidrocarburos\r\n"
        "2026-09-30,123,MALO,2010-01-01,-,agente de retención del IGV\r\n"
    )
    archive = tmp_path / "padron_agentes_retencion_percepcion_igv_202609.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("padron_agentes_retencion_percepcion_igv_202609.csv", csv.encode("utf-8"))

    records = list(read_agents(archive))

    assert [r.agent_type if r else None for r in records] == [
        AgentType.WITHHOLDING,
        AgentType.PERCEPTION_DOMESTIC_SALES,
        AgentType.PERCEPTION_FUEL,
        None,
    ]
    first = records[0]
    assert first is not None and first.since == date(2002, 6, 1) and first.resolution == "R.S. 037-2002"


def test_unknown_agent_roles_are_not_guessed() -> None:
    assert agent_type_from_label("otro régimen") is None
