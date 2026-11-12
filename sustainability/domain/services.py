"""The rules that decide whether a certificate makes a MYPE green: ``green-v1``.

Fixed rules, not a model: the reader only extracts facts from the document,
and these checks decide. Each one is kept with its result, so the decision can
always be explained (US10). They check that the certificate is coherent with
the public registries, not that it is authentic: a well-made forgery passes.
See ``docs/GREEN_RULES.md``.
"""
from datetime import date

from shared.domain.names import normalize_company_name
from sustainability.domain.value_objects import (
    CertificateExtraction,
    CompanyStanding,
    CriterionCode,
    CriterionResult,
    GreenStandard,
    Ruc,
)

RULES_VERSION = "green-v1"
ACCEPTED_STANDARDS = "ISO 14001 o ISO 50001"

class GreenCertificationPolicy:
    """Checks a certificate against the ``green-v1`` rules."""

    version = RULES_VERSION

    def evaluate(
        self,
        extraction: CertificateExtraction | None,
        ruc: Ruc,
        standing: CompanyStanding,
        today: date,
        *,
        unreadable_reason: str | None = None,
    ) -> tuple[CriterionResult, ...]:
        """Check a certificate; it is green only if it passes every check.

        Args:
            extraction (CertificateExtraction | None): What the reader found;
                ``None`` if the document could not be read.
            ruc (Ruc): The MYPE's RUC.
            standing (CompanyStanding): What the registries say about that RUC.
            today (date): The day of the decision, in Lima.
            unreadable_reason (str | None): Why the document could not be read, when it could not.

        Returns:
            tuple[CriterionResult, ...]: Every check made. An unreadable
            document stops at the first one, since the others need its facts.
        """
        if extraction is None or not extraction.is_certificate:
            reason = unreadable_reason or "El documento no es un certificado de un sistema de gestión"
            return (CriterionResult(CriterionCode.CERTIFICATE_READABLE, False, reason),)
        return (
            CriterionResult(CriterionCode.CERTIFICATE_READABLE, True, "Se leyó el certificado"),
            self._standard(extraction),
            self._in_force(extraction, today),
            self._holder(extraction, ruc, standing),
            self._environmental_offender(standing),
        )

    @staticmethod
    def is_green(criteria: tuple[CriterionResult, ...]) -> bool:
        """Whether a set of checks makes a certificate green: all five made, and all passed."""
        return {result.code for result in criteria} == set(CriterionCode) and all(r.passed for r in criteria)

    @staticmethod
    def _standard(extraction: CertificateExtraction) -> CriterionResult:
        printed = extraction.standard_text or "sin norma legible"
        if extraction.standard is None:
            return CriterionResult(
                CriterionCode.ACCEPTED_STANDARD, False, f"La norma ({printed}) no es {ACCEPTED_STANDARDS}"
            )
        label = {GreenStandard.ISO_14001: "ISO 14001", GreenStandard.ISO_50001: "ISO 50001"}[extraction.standard]
        return CriterionResult(CriterionCode.ACCEPTED_STANDARD, True, f"Certifica {label} ({printed})")

    @staticmethod
    def _in_force(extraction: CertificateExtraction, today: date) -> CriterionResult:
        if extraction.valid_until is None:
            return CriterionResult(CriterionCode.IN_FORCE, False, "El certificado no indica fecha de vencimiento")
        if extraction.issued_on is not None and extraction.issued_on > today:
            return CriterionResult(
                CriterionCode.IN_FORCE, False, f"La fecha de emisión ({extraction.issued_on.isoformat()}) es futura"
            )
        if extraction.valid_until < today:
            return CriterionResult(CriterionCode.IN_FORCE, False, f"Venció el {extraction.valid_until.isoformat()}")
        return CriterionResult(CriterionCode.IN_FORCE, True, f"Vigente hasta el {extraction.valid_until.isoformat()}")

    @staticmethod
    def _holder(extraction: CertificateExtraction, ruc: Ruc, standing: CompanyStanding) -> CriterionResult:
        code = CriterionCode.HOLDER_MATCHES_SUNAT
        if not standing.registry_loaded:
            return CriterionResult(code, False, "No se pudo consultar el padrón de SUNAT")
        if standing.registered_name is None:
            return CriterionResult(code, False, f"El RUC {ruc.value} no figura en el padrón de SUNAT")
        if extraction.holder_name is None:
            return CriterionResult(code, False, "El certificado no indica a qué empresa se emitió")
        printed_ruc = "".join(char for char in extraction.holder_ruc or "" if char.isdigit())
        if printed_ruc and printed_ruc != ruc.value:
            return CriterionResult(code, False, f"El certificado es del RUC {printed_ruc}, no del {ruc.value}")
        if normalize_company_name(extraction.holder_name) != normalize_company_name(standing.registered_name):
            return CriterionResult(
                code,
                False,
                f"El titular «{extraction.holder_name}» no coincide con la razón social en SUNAT "
                f"«{standing.registered_name}»",
            )
        return CriterionResult(
            code, True, f"El titular coincide con la razón social en SUNAT «{standing.registered_name}»"
        )

    @staticmethod
    def _environmental_offender(standing: CompanyStanding) -> CriterionResult:
        code = CriterionCode.NOT_ENVIRONMENTAL_OFFENDER
        if not standing.environmental_registry_loaded:
            return CriterionResult(code, False, "No se pudo consultar el registro de infractores de OEFA")
        if standing.environmental_infractions > 0:
            return CriterionResult(
                code,
                False,
                f"Figura en el registro de infractores ambientales de OEFA "
                f"({standing.environmental_infractions} infracción(es))",
            )
        return CriterionResult(code, True, "No figura en el registro de infractores ambientales de OEFA")
