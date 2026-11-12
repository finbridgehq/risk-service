"""Checking a ficha RUC's signature and reading its text, on demonstration fichas.

No real ficha is ever kept in the repository: each test signs its own with a CA
created for the session. SUNAT's own chain is exercised by a CA whose signer
carries SUNAT's organization, standing in for Llama.pe's.
"""

from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from pyhanko.pdf_utils.generic import NameObject, TextStringObject
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

from verification.domain.value_objects import RucDocumentFacts, SignatureAuthority
from verification.infrastructure.demo import DemoFicha, build_demo_ficha, create_demo_ca, sign_demo_ficha
from verification.infrastructure.inspector import (
    MODIFIED,
    NOT_COVERED,
    NOT_SIGNED,
    NOT_SUNAT,
    SUNAT_ORGANIZATION,
    UNREADABLE_PDF,
    PdfRucDocumentInspector,
    load_certificate,
    read_facts,
)

FICHA = DemoFicha(ruc="20601234567", name="TEXTILES ANDINOS S.A.C.", issued_on=date(2026, 10, 27))


@pytest.fixture(scope="session")
def demo_ca(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("demo-ca")
    create_demo_ca(directory)
    return directory


@pytest.fixture(scope="session")
def sunat_like_ca(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("sunat-like-ca")
    create_demo_ca(directory, signer_organization=SUNAT_ORGANIZATION)
    return directory


def inspector(sunat: Path | None = None, demo: Path | None = None) -> PdfRucDocumentInspector:
    sunat_root = load_certificate(sunat / "ca.pem") if sunat else PdfRucDocumentInspector.pinned()._sunat_root
    return PdfRucDocumentInspector(sunat_root, (), load_certificate(demo / "ca.pem") if demo else None)


def test_the_facts_are_read_from_the_text() -> None:
    assert read_facts(build_demo_ficha(FICHA)) == RucDocumentFacts(
        ruc="20601234567",
        name="TEXTILES ANDINOS S.A.C.",
        status="ACTIVO",
        domicile_condition="HABIDO",
        issued_on=date(2026, 10, 27),
    )


def test_a_name_on_two_lines_is_joined_and_a_two_word_condition_is_kept() -> None:
    ficha = DemoFicha(
        ruc="20601234567", name="TEXTILES\nANDINOS", issued_on=date(2026, 10, 27), domicile_condition="NO HABIDO"
    )

    facts = read_facts(build_demo_ficha(ficha))

    assert facts.name == "TEXTILES ANDINOS"
    assert facts.domicile_condition == "NO HABIDO"


def test_a_ficha_signed_by_sunat_is_sunat_s(sunat_like_ca: Path) -> None:
    inspection = inspector(sunat=sunat_like_ca).inspect(sign_demo_ficha(build_demo_ficha(FICHA), sunat_like_ca))

    assert inspection.authority is SignatureAuthority.SUNAT
    assert inspection.facts is not None and inspection.facts.ruc == "20601234567"


def test_another_organization_on_sunat_s_chain_is_not_sunat(demo_ca: Path) -> None:
    # Llama.pe issues certificates to many: the chain alone is not enough.
    inspection = inspector(sunat=demo_ca).inspect(sign_demo_ficha(build_demo_ficha(FICHA), demo_ca))

    assert inspection.authority is None
    assert inspection.signature_problem == NOT_SUNAT


def test_the_demonstration_signature_counts_only_when_its_ca_is_set(demo_ca: Path) -> None:
    signed = sign_demo_ficha(build_demo_ficha(FICHA), demo_ca)

    assert inspector(demo=demo_ca).inspect(signed).authority is SignatureAuthority.DEMO
    assert inspector().inspect(signed).signature_problem == NOT_SUNAT


def test_a_ficha_signed_by_another_ca_is_not_trusted(demo_ca: Path, tmp_path: Path) -> None:
    create_demo_ca(tmp_path)

    inspection = inspector(demo=demo_ca).inspect(sign_demo_ficha(build_demo_ficha(FICHA), tmp_path))

    assert inspection.signature_problem == NOT_SUNAT


def test_an_unsigned_ficha_says_so_but_is_still_read(demo_ca: Path) -> None:
    inspection = inspector(demo=demo_ca).inspect(build_demo_ficha(FICHA))

    assert inspection.signature_problem == NOT_SIGNED
    assert inspection.facts is not None and inspection.facts.ruc == "20601234567"


def test_a_ficha_edited_after_it_was_signed_is_invalid(demo_ca: Path) -> None:
    signed = sign_demo_ficha(build_demo_ficha(FICHA), demo_ca)

    inspection = inspector(demo=demo_ca).inspect(signed.replace(b"20601234567", b"20601234568", 1))

    assert inspection.signature_problem == MODIFIED


def test_a_ficha_with_an_update_appended_after_the_signature_is_not_covered(demo_ca: Path) -> None:
    writer = IncrementalPdfFileWriter(BytesIO(sign_demo_ficha(build_demo_ficha(FICHA), demo_ca)))
    writer.root[NameObject("/Lang")] = TextStringObject("es-PE")
    writer.update_root()  # type: ignore[no-untyped-call]
    appended = BytesIO()
    writer.write(appended)  # type: ignore[no-untyped-call]

    inspection = inspector(demo=demo_ca).inspect(appended.getvalue())

    assert inspection.signature_problem == NOT_COVERED


def test_a_file_that_is_not_a_pdf_is_unusable() -> None:
    inspection = inspector().inspect(b"%PDF-1.7 not really a pdf")

    assert inspection.signature_problem == UNREADABLE_PDF
    assert inspection.facts is None


def test_the_pinned_chain_is_llama_pe_s() -> None:
    pinned = PdfRucDocumentInspector.pinned()

    assert pinned._sunat_root.subject.native["common_name"] == "Llama.pe Root CA"
    assert pinned._sunat_root.sha256.hex().upper().startswith("228CA84D00687D20")
    assert [c.subject.native["common_name"] for c in pinned._sunat_intermediates] == ["Llama.pe SHA256 Standard CA"]
