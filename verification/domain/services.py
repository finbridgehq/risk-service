"""The rules that decide whether a MYPE is who it says it is: ``kyc-v1``.

Fixed rules, not a model. The ficha RUC proves itself with SUNAT's digital
signature, which covers the whole file, so what it prints can be trusted
without visiting SUNAT's website; the padrón and the SSCO list say the rest.
Each check is kept with its result, so the decision can always be explained.
See ``docs/KYC_RULES.md``.
"""
from datetime import date, timedelta

from shared.domain.names import normalize_company_name
from verification.domain.value_objects import (
    Applicant,
    CheckCode,
    CheckResult,
    Evidence,
    EvidenceCode,
    FieldError,
    FieldErrorCode,
    KycAssessment,
    RucDocumentFacts,
    RucDocumentInspection,
    SignatureAuthority,
    TaxpayerStanding,
    VerificationDecision,
)

RULES_VERSION = "kyc-v1"
MAX_DOCUMENT_AGE = timedelta(days=30)
ACTIVE = "ACTIVO"
FOUND = "HABIDO"


class KycPolicy:
    """Checks a MYPE against the ``kyc-v1`` rules."""

    version = RULES_VERSION

    def evaluate(
        self, applicant: Applicant, inspection: RucDocumentInspection, standing: TaxpayerStanding, today: date
    ) -> KycAssessment:
        """Make every check of the rules.

        When the RUC is not in the padrón (new taxpayers take a while to appear
        in it), a ficha signed by SUNAT for that RUC stands in for it: its
        status and its address condition are used instead, and the check says so.

        Args:
            applicant (Applicant): What the MYPE declared.
            inspection (RucDocumentInspection): Its ficha RUC's signature and text.
            standing (TaxpayerStanding): What the registries say about the declared RUC.
            today (date): The day of the decision, in Lima.

        Returns:
            KycAssessment: Every check, the fields to correct, the sanctions
            that do not reject, and whether the ficha is a demonstration one.
        """
        facts = inspection.facts or RucDocumentFacts()
        from_ficha = not standing.found and inspection.signed and facts.ruc == applicant.ruc.value
        source = "el padrón de SUNAT" if standing.found else "la ficha RUC"
        status = standing.status if standing.found else facts.status if from_ficha else None
        condition = standing.domicile_condition if standing.found else facts.domicile_condition if from_ficha else None
        reference_name = standing.registered_name if standing.found else facts.name if from_ficha else None

        field_errors: list[FieldError] = []
        found = self._found(applicant, standing, from_ficha)
        if not found.passed:
            field_errors.append(FieldError("rucNumber", FieldErrorCode.RUC_NOT_FOUND))
        name, declared_name_only = self._name(applicant, facts, reference_name)
        if declared_name_only:
            field_errors.append(FieldError("businessName", FieldErrorCode.NAME_MISMATCH))
        return KycAssessment(
            checks=(
                found,
                self._signed(inspection),
                self._recent(facts, today),
                self._matches(applicant, facts),
                name,
                self._active(status, source),
                self._domicile(condition, source),
                self._not_shell(standing),
            ),
            field_errors=tuple(field_errors),
            evidence=self._evidence(standing),
            demo=inspection.demo,
        )

    @staticmethod
    def decide(assessment: KycAssessment) -> VerificationDecision:
        """Turn the checks into a decision.

        A RUC SUNAT does not know is a typo to correct, whatever else failed: the
        other checks were made against the wrong taxpayer. A declared name that
        differs from SUNAT's is to correct too, but only if nothing else failed.
        Any other failure rejects.

        Args:
            assessment (KycAssessment): What :meth:`evaluate` found.

        Returns:
            VerificationDecision: The decision.
        """
        failed = {result.code for result in assessment.checks if not result.passed}
        codes = {error.code for error in assessment.field_errors}
        if FieldErrorCode.RUC_NOT_FOUND in codes:
            return VerificationDecision.CORRECTION_REQUIRED
        if not failed and {result.code for result in assessment.checks} == set(CheckCode):
            return VerificationDecision.VERIFIED
        if FieldErrorCode.NAME_MISMATCH in codes and failed == {CheckCode.NAME_MATCHES}:
            return VerificationDecision.CORRECTION_REQUIRED
        return VerificationDecision.REJECTED

    @staticmethod
    def _found(applicant: Applicant, standing: TaxpayerStanding, from_ficha: bool) -> CheckResult:
        code = CheckCode.TAXPAYER_FOUND
        if standing.found:
            return CheckResult(code, True, "Figura en el padrón de SUNAT")
        if from_ficha:
            return CheckResult(
                code, True, "No figura aún en el padrón de SUNAT; el estado se tomó de la ficha RUC firmada"
            )
        return CheckResult(
            code, False, f"El RUC {applicant.ruc.value} no figura en el padrón de SUNAT ni en una ficha RUC firmada"
        )

    @staticmethod
    def _signed(inspection: RucDocumentInspection) -> CheckResult:
        code = CheckCode.RUC_DOCUMENT_SIGNED
        if inspection.authority is SignatureAuthority.SUNAT:
            return CheckResult(code, True, "La ficha RUC está firmada digitalmente por SUNAT")
        if inspection.authority is SignatureAuthority.DEMO:
            return CheckResult(code, True, "Firma de demostración de Vankoo, no de SUNAT")
        return CheckResult(code, False, inspection.signature_problem or "La ficha RUC no está firmada por SUNAT")

    @staticmethod
    def _recent(facts: RucDocumentFacts, today: date) -> CheckResult:
        code = CheckCode.RUC_DOCUMENT_RECENT
        if facts.issued_on is None:
            return CheckResult(code, False, "La ficha RUC no indica su fecha de emisión")
        issued = facts.issued_on.isoformat()
        if facts.issued_on > today:
            return CheckResult(code, False, f"La fecha de emisión de la ficha RUC ({issued}) es futura")
        if today - facts.issued_on > MAX_DOCUMENT_AGE:
            return CheckResult(
                code, False, f"La ficha RUC se emitió el {issued}; debe tener {MAX_DOCUMENT_AGE.days} días o menos"
            )
        return CheckResult(code, True, f"La ficha RUC se emitió el {issued}")

    @staticmethod
    def _matches(applicant: Applicant, facts: RucDocumentFacts) -> CheckResult:
        code = CheckCode.RUC_DOCUMENT_MATCHES
        if facts.ruc is None:
            return CheckResult(code, False, "No se encontró el RUC en la ficha")
        if facts.ruc != applicant.ruc.value:
            return CheckResult(code, False, f"La ficha es del RUC {facts.ruc}, no del {applicant.ruc.value}")
        return CheckResult(code, True, f"La ficha es del RUC {applicant.ruc.value}")

    @staticmethod
    def _name(applicant: Applicant, facts: RucDocumentFacts, reference: str | None) -> tuple[CheckResult, bool]:
        code = CheckCode.NAME_MATCHES
        if reference is None:
            return CheckResult(code, False, "No hay una razón social de SUNAT con la que comparar"), False
        if facts.name is None:
            return CheckResult(code, False, "No se encontró la razón social en la ficha"), False
        if normalize_company_name(facts.name) != normalize_company_name(reference):
            return CheckResult(
                code, False, f"La ficha es de «{facts.name}», no de «{reference}» como dice SUNAT"
            ), False
        if normalize_company_name(applicant.business_name) != normalize_company_name(reference):
            return CheckResult(
                code,
                False,
                f"La razón social declarada «{applicant.business_name}» no coincide con la de SUNAT «{reference}»",
            ), True
        return CheckResult(code, True, f"La razón social coincide con la de SUNAT «{reference}»"), False

    @staticmethod
    def _active(status: str | None, source: str) -> CheckResult:
        code = CheckCode.TAXPAYER_ACTIVE
        if status is None:
            return CheckResult(code, False, "No se pudo saber el estado del contribuyente")
        if status != ACTIVE:
            return CheckResult(code, False, f"El contribuyente figura como {status} en {source}")
        return CheckResult(code, True, f"El contribuyente figura como {ACTIVE} en {source}")

    @staticmethod
    def _domicile(condition: str | None, source: str) -> CheckResult:
        code = CheckCode.DOMICILE_FOUND
        if condition is None:
            return CheckResult(code, False, "No se pudo saber la condición del domicilio fiscal")
        if condition != FOUND:
            return CheckResult(code, False, f"El domicilio fiscal figura como {condition} en {source}")
        return CheckResult(code, True, f"El domicilio fiscal figura como {FOUND} en {source}")

    @staticmethod
    def _not_shell(standing: TaxpayerStanding) -> CheckResult:
        code = CheckCode.NOT_SHELL_COMPANY
        if standing.shell_company:
            return CheckResult(
                code, False, "Figura en la lista de SUNAT de empresas sin capacidad operativa (SSCO)"
            )
        return CheckResult(code, True, "No figura en la lista de SUNAT de empresas sin capacidad operativa")

    @staticmethod
    def _evidence(standing: TaxpayerStanding) -> tuple[Evidence, ...]:
        evidence: list[Evidence] = []
        if standing.coactive_debt is not None:
            evidence.append(
                Evidence(
                    EvidenceCode.COACTIVE_DEBT,
                    f"Tiene deuda en cobranza coactiva de SUNAT por S/ {standing.coactive_debt:,.2f}",
                )
            )
        if standing.oece_sanctions > 0:
            evidence.append(
                Evidence(EvidenceCode.OECE_SANCTION, f"Tiene {standing.oece_sanctions} sanción(es) del OECE vigentes")
            )
        if standing.environmental_infractions > 0:
            evidence.append(
                Evidence(
                    EvidenceCode.ENVIRONMENTAL_OFFENDER,
                    f"Figura en el registro de infractores ambientales de OEFA "
                    f"({standing.environmental_infractions} infracción(es))",
                )
            )
        return tuple(evidence)
