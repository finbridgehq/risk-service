"""Adapter that checks a ficha RUC's digital signature and reads its text, offline.

SUNAT signs every ficha RUC it issues (``adbe.pkcs7.detached``, SHA-256) with
the certificate of its «AGENTE AUTOMATIZADO», issued by Llama.pe. The ficha is
genuine when that signature is valid, covers the whole file, chains up to the
Llama.pe root this service pins (``trust/``), and the signer's organization is
SUNAT's: Llama.pe issues certificates to many others, so the chain alone is not
enough. Nothing is fetched: no OCSP, no CRL, no SUNAT website. A ficha that was
edited after SUNAT signed it fails, because the signature no longer covers it.

The embedded timestamp (from a TSA SUNAT uses) is not checked: its root is not
pinned, and the ficha's own date is checked by the rules instead.

The text is read with pypdf, which returns the lines in the order the PDF draws
them: the header «Reporte de Ficha RUC», then the name (one or more lines), the
bare RUC and «Fecha: dd/mm/aaaa»; elsewhere «Estado del Contribuyente …» and
«Condición del Domicilio Fiscal …». Only fichas of a RUC 10 were seen; a RUC 20
ficha is expected to share the header. See ``docs/KYC_RULES.md``.
"""
import logging
import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from asn1crypto import pem, x509
from pyhanko.pdf_utils.misc import PdfError as PyHankoPdfError
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.errors import SignatureValidationError
from pyhanko.sign.validation.status import PdfSignatureStatus, SignatureCoverageLevel
from pyhanko_certvalidator import ValidationContext
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from verification.application.outbound_services import RucDocumentInspector
from verification.domain.value_objects import RucDocumentFacts, RucDocumentInspection, SignatureAuthority

logger = logging.getLogger(__name__)

TRUST_DIRECTORY = Path(__file__).parent / "trust"
SUNAT_ROOT = TRUST_DIRECTORY / "llama-pe-root-ca.pem"
SUNAT_INTERMEDIATE = TRUST_DIRECTORY / "llama-pe-sha256-standard-ca.pem"
SUNAT_ORGANIZATION = "SUPERINTENDENCIA NACIONAL DE ADUANAS Y DE ADMINISTRACION TRIBUTARIA - SUNAT"

HEADER = re.compile(r"^Reporte de Ficha RUC\b", re.IGNORECASE)
BARE_RUC = re.compile(r"^\d{11}$")
STATUS = re.compile(r"^Estado del Contribuyente\s*:?\s*(.*)$", re.IGNORECASE)
CONDITION = re.compile(r"^Condici[oó]n del Domicilio Fiscal\s*:?\s*(.*)$", re.IGNORECASE)
ISSUED = re.compile(r"\bFecha\s*:\s*(\d{2}/\d{2}/\d{4})")

NOT_SIGNED = "La ficha RUC no tiene firma digital"
MODIFIED = "La firma digital no es válida: la ficha RUC se modificó después de firmarse"
NOT_COVERED = "La firma digital no cubre todo el documento: la ficha RUC se modificó después de firmarse"
NOT_SUNAT = "La ficha RUC está firmada, pero no por SUNAT"
UNREADABLE_SIGNATURE = "No se pudo leer la firma digital de la ficha RUC"
UNREADABLE_PDF = "La ficha RUC no es un PDF legible"


def load_certificate(path: Path) -> x509.Certificate:
    """Read a PEM or DER certificate.

    Args:
        path (Path): The file.

    Returns:
        x509.Certificate: The certificate.
    """
    data = path.read_bytes()
    if pem.detect(data):
        _, _, data = pem.unarmor(data)
    return x509.Certificate.load(data)


class PdfRucDocumentInspector(RucDocumentInspector):
    """Checks fichas RUC against SUNAT's pinned certificate chain, and the demo one when set."""

    def __init__(
        self,
        sunat_root: x509.Certificate,
        sunat_intermediates: tuple[x509.Certificate, ...],
        demo_root: x509.Certificate | None = None,
    ) -> None:
        """Initialize the inspector with the roots it trusts.

        Args:
            sunat_root (x509.Certificate): Llama.pe's root, which SUNAT's signer chains to.
            sunat_intermediates (tuple[x509.Certificate, ...]): The CAs between them.
            demo_root (x509.Certificate | None): Vankoo's demonstration CA, when
                ``KYC_DEMO_CA_PATH`` is set; a temporary patch for the demonstrations.
        """
        self._sunat_root = sunat_root
        self._sunat_intermediates = sunat_intermediates
        self._demo_root = demo_root

    @classmethod
    def pinned(cls, demo_ca_path: Path | None = None) -> "PdfRucDocumentInspector":
        """Build the inspector on the certificates kept in ``trust/``, plus the demo CA if given."""
        return cls(
            load_certificate(SUNAT_ROOT),
            (load_certificate(SUNAT_INTERMEDIATE),),
            load_certificate(demo_ca_path) if demo_ca_path is not None else None,
        )

    def inspect(self, content: bytes) -> RucDocumentInspection:
        try:
            facts = read_facts(content)
        except (PdfReadError, ValueError, KeyError, TypeError) as error:
            logger.warning("Could not read the text of a ficha RUC: %s", error)
            return RucDocumentInspection.unusable(UNREADABLE_PDF)
        authority, problem = self._signature(content)
        return RucDocumentInspection(authority=authority, signature_problem=problem, facts=facts)

    def _signature(self, content: bytes) -> tuple[SignatureAuthority | None, str | None]:
        try:
            signatures = PdfFileReader(BytesIO(content), strict=False).embedded_signatures
            if not signatures:
                return None, NOT_SIGNED
            # The last signature is the only one that can cover the whole file.
            signature = signatures[-1]
            status = validate_pdf_signature(signature, self._context(self._sunat_root, self._sunat_intermediates))
            problem = _integrity_problem(status)
            if problem is not None:
                return None, problem
            if status.trusted and _organization(status) == SUNAT_ORGANIZATION:
                return SignatureAuthority.SUNAT, None
            if self._demo_root is not None:
                demo = validate_pdf_signature(signature, self._context(self._demo_root, ()))
                if _integrity_problem(demo) is None and demo.trusted:
                    return SignatureAuthority.DEMO, None
            return None, NOT_SUNAT
        except (SignatureValidationError, PyHankoPdfError, PdfReadError, ValueError, KeyError, TypeError) as error:
            logger.warning("Could not validate the signature of a ficha RUC: %s", error)
            return None, UNREADABLE_SIGNATURE

    @staticmethod
    def _context(root: x509.Certificate, intermediates: tuple[x509.Certificate, ...]) -> ValidationContext:
        # Offline on purpose: the chain is pinned, and revocation is not checked.
        return ValidationContext(
            trust_roots=[root], other_certs=list(intermediates), allow_fetching=False, revocation_mode="soft-fail"
        )


def _integrity_problem(status: PdfSignatureStatus) -> str | None:
    if not status.intact or not status.valid:
        return MODIFIED
    if status.coverage is not SignatureCoverageLevel.ENTIRE_FILE:
        return NOT_COVERED
    return None


def _organization(status: PdfSignatureStatus) -> str | None:
    value = status.signing_cert.subject.native.get("organization_name")
    return value if isinstance(value, str) else None


def read_facts(content: bytes) -> RucDocumentFacts:
    """Read the RUC, the name, the status, the address condition and the date a ficha RUC prints.

    Args:
        content (bytes): The PDF.

    Returns:
        RucDocumentFacts: What was found; a missing fact is ``None``.

    Raises:
        PdfReadError: If the file is not a readable PDF.
    """
    reader = PdfReader(BytesIO(content), strict=False)
    lines = [" ".join(line.split()) for page in reader.pages for line in (page.extract_text() or "").splitlines()]
    lines = [line for line in lines if line]
    ruc, name = _ruc_and_name(lines)
    return RucDocumentFacts(
        ruc=ruc,
        name=name,
        status=_labelled(lines, STATUS),
        domicile_condition=_labelled(lines, CONDITION),
        issued_on=_issued_on("\n".join(lines)),
    )


def _ruc_and_name(lines: list[str]) -> tuple[str | None, str | None]:
    header = next((index for index, line in enumerate(lines) if HEADER.match(line)), None)
    start = header + 1 if header is not None else 0
    ruc_index = next((index for index in range(start, len(lines)) if BARE_RUC.fullmatch(lines[index])), None)
    if ruc_index is None:
        return None, None
    name_lines = lines[start:ruc_index] if header is not None else lines[ruc_index - 1 : ruc_index]
    return lines[ruc_index], " ".join(name_lines) or None


def _labelled(lines: list[str], label: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines):
        match = label.match(line)
        if match is None:
            continue
        value = match.group(1).strip()
        if not value and index + 1 < len(lines):
            value = lines[index + 1]
        return value or None
    return None


def _issued_on(text: str) -> date | None:
    match = ISSUED.search(text)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None
