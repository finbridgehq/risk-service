"""Demonstration fichas RUC, signed by a local certificate of Vankoo's.

TEMPORARY PATCH for the demonstrations: a real ficha RUC carries a person's or
a company's data, so the demos use made-up ones. They look like a ficha to the
inspector (the same header, labels and date) but every page says «DOCUMENTO DE
DEMOSTRACIÓN — NO VÁLIDO», and they are signed by a CA created on the machine
that runs the demo, never by SUNAT. The service accepts that CA only when
``KYC_DEMO_CA_PATH`` points to it, and every decision on such a ficha is marked
``demo``. Remove this module, the CLI commands and the setting when the demos end.
See ``docs/KYC_RULES.md``.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.keys import load_private_key_from_pemder
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko_certvalidator.registry import SimpleCertificateStore

from verification.infrastructure.inspector import load_certificate

DEMO_ORGANIZATION = "VANKOO - DEMOSTRACION"
DEMO_NOTICE = "DOCUMENTO DE DEMOSTRACIÓN — NO VÁLIDO"
CA_CERTIFICATE = "ca.pem"
CA_KEY = "ca.key"
SIGNER_CERTIFICATE = "signer.pem"
SIGNER_KEY = "signer.key"
VALIDITY = timedelta(days=730)


@dataclass(frozen=True, slots=True)
class DemoFicha:
    """What a demonstration ficha prints.

    Attributes:
        ruc (str): The RUC it reports on.
        name (str): The taxpayer's name; a line break prints it on two lines,
            as SUNAT does with a long business name.
        issued_on (date): The date it prints as «Fecha:».
        status (str): «Estado del Contribuyente».
        domicile_condition (str): «Condición del Domicilio Fiscal».
    """

    ruc: str
    name: str
    issued_on: date
    status: str = "ACTIVO"
    domicile_condition: str = "HABIDO"


def create_demo_ca(
    directory: Path, now: datetime | None = None, *, signer_organization: str = DEMO_ORGANIZATION
) -> Path:
    """Create the demonstration CA and its signing certificate, unless they exist.

    Args:
        directory (Path): Where to keep them; it must stay out of git.
        now (datetime | None): When they start to be valid; now by default.
        signer_organization (str): The signer's organization; the tests set
            SUNAT's to check the inspector's rule on it.

    Returns:
        Path: The CA certificate, the file ``KYC_DEMO_CA_PATH`` points to.
    """
    directory.mkdir(parents=True, exist_ok=True)
    ca_path = directory / CA_CERTIFICATE
    if ca_path.exists() and (directory / SIGNER_CERTIFICATE).exists():
        return ca_path
    start = (now or datetime.now(UTC)) - timedelta(days=1)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = _name("Vankoo Demo CA (no valida)")
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_key_usage(ca=True), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    signer_key = ec.generate_private_key(ec.SECP256R1())
    signer = (
        x509.CertificateBuilder()
        .subject_name(_name("Vankoo Demo - Ficha RUC (no valida)", signer_organization))
        .issuer_name(ca_name)
        .public_key(signer_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(ca=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    for path, key in ((directory / CA_KEY, ca_key), (directory / SIGNER_KEY, signer_key)):
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        path.chmod(0o600)
    (directory / SIGNER_CERTIFICATE).write_bytes(signer.public_bytes(serialization.Encoding.PEM))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    return ca_path


def build_demo_ficha(ficha: DemoFicha) -> bytes:
    """Write an unsigned demonstration ficha: one page, the labels the inspector reads.

    Args:
        ficha (DemoFicha): What it prints.

    Returns:
        bytes: The PDF.
    """
    lines = [
        (16, DEMO_NOTICE),
        (13, "Reporte de Ficha RUC"),
        *((11, line) for line in ficha.name.splitlines()),
        (11, ficha.ruc),
        (10, f"Fecha: {ficha.issued_on.strftime('%d/%m/%Y')}"),
        (10, "Información del Contribuyente"),
        (10, f"Estado del Contribuyente {ficha.status}"),
        (10, f"Condición del Domicilio Fiscal {ficha.domicile_condition}"),
        (9, "Generado por Vankoo para demostraciones. No es un documento de SUNAT."),
        (16, DEMO_NOTICE),
    ]
    stream = bytearray(b"BT\n")
    y = 790
    for size, text in lines:
        stream += f"/F1 {size} Tf 1 0 0 1 50 {y} Tm (".encode() + _pdf_text(text) + b") Tj\n"
        y -= size + 14
    stream += b"ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + bytes(stream) + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(pdf)


def sign_demo_ficha(pdf: bytes, directory: Path) -> bytes:
    """Sign a ficha with the demonstration certificate in ``directory``.

    Args:
        pdf (bytes): The unsigned ficha.
        directory (Path): Where :func:`create_demo_ca` left the certificates.

    Returns:
        bytes: The signed ficha; the signature covers the whole file.
    """
    registry = SimpleCertificateStore()  # type: ignore[no-untyped-call]  # its constructor has no annotations
    registry.register(load_certificate(directory / CA_CERTIFICATE))
    signer = signers.SimpleSigner(
        signing_cert=load_certificate(directory / SIGNER_CERTIFICATE),
        signing_key=load_private_key_from_pemder(str(directory / SIGNER_KEY), passphrase=None),
        cert_registry=registry,
    )
    output = signers.sign_pdf(
        IncrementalPdfFileWriter(BytesIO(pdf)),
        signers.PdfSignatureMetadata(field_name="Signature1", md_algorithm="sha256", reason=DEMO_NOTICE),
        signer=signer,
    )
    return bytes(output.getvalue())


def _name(common_name: str, organization: str = DEMO_ORGANIZATION) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _key_usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not ca,
        content_commitment=not ca,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


def _pdf_text(text: str) -> bytes:
    return text.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
