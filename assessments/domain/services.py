"""Domain services of the Assessments bounded context.

The grading policy is the rule that turns what we know about an auction and
its payer into a decision. It belongs to no single aggregate: it reads facts
Investment published, what the public registries say and what a credit bureau
reports. It is a port, so a new
policy replaces it without touching the assessment, the consumer or the
delivery. The rules of the current one are in ``docs/SCORING_RULES.md``.
"""
import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from assessments.domain.value_objects import (
    AuctionFacts,
    CreditReport,
    GradingDecision,
    NewsCheck,
    NewsCheckStatus,
    NewsFinding,
    NewsSeverity,
    PayerStanding,
    RiskGrade,
    SbsRating,
    ScoreFactor,
)

POINTS_POLICY_VERSION = "points-v3"
BASE_SCORE = 40
GRADE_A_FROM = 75
GRADE_B_FROM = 55
NAME_MATCH_THRESHOLD = 0.85

PAYER_NOT_IN_REGISTRY = "PAYER_NOT_IN_REGISTRY"
PAYER_NOT_ACTIVE = "PAYER_NOT_ACTIVE"
PAYER_DOMICILE_NOT_FOUND = "PAYER_DOMICILE_NOT_FOUND"
PAYER_SHELL_COMPANY = "PAYER_SHELL_COMPANY"

CREDIT_RATING_POINTS = {
    SbsRating.NORMAL: ("CREDIT_RATING_NORMAL", 0, "Normal"),
    SbsRating.POTENTIAL_PROBLEMS: ("CREDIT_RATING_CPP", -10, "CPP (con problemas potenciales)"),
    SbsRating.DEFICIENT: ("CREDIT_RATING_DEFICIENT", -20, "Deficiente"),
    SbsRating.DOUBTFUL: ("CREDIT_RATING_DOUBTFUL", -30, "Dudoso"),
    SbsRating.LOSS: ("CREDIT_RATING_LOSS", -40, "Pérdida"),
}

# At most -30 in all: one serious factor and one moderate, however many pieces of news.
NEWS_SERIOUS_POINTS = -20
NEWS_MODERATE_POINTS = -10
NEWS_HEADLINES_SHOWN = 2

SOURCE_NAMES = {
    "sunat-ssco": "lista de SUNAT de sujetos sin capacidad operativa",
    "sunat-deuda-coactiva": "lista de SUNAT de deuda en cobranza coactiva",
    "oece-inhabilitados": "lista de OECE de proveedores inhabilitados",
    "oece-multas": "lista de OECE de multas",
    "oefa-ruias": "registro de OEFA de infractores ambientales",
}

ACTIVE_STATUS = "ACTIVO"
FOUND_CONDITION = "HABIDO"
UNVERIFIED_CONDITIONS = ("PENDIENTE", "POR VERIFICAR")
NOT_FOUND_CONDITIONS = ("NO HABIDO", "NO HALLADO")

# Legal-form suffixes that SUNAT and an invoice may write differently
# (``S.A.C.`` against ``SOCIEDAD ANONIMA CERRADA``) and that say nothing about who it is.
_LEGAL_FORMS = (
    "SOCIEDAD COMERCIAL DE RESPONSABILIDAD LIMITADA",
    "EMPRESA INDIVIDUAL DE RESPONSABILIDAD LIMITADA",
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "SOCIEDAD ANONIMA ABIERTA",
    "SOCIEDAD ANONIMA CERRADA",
    "SOCIEDAD ANONIMA",
)
_LEGAL_FORM_TOKENS = frozenset({"SAC", "SA", "SAA", "SRL", "EIRL", "SCRL"})


class RiskGradingPolicy(ABC):
    """Decides whether an auction can be funded, and its grade, with no I/O."""

    @abstractmethod
    def grade(
        self,
        facts: AuctionFacts,
        standing: PayerStanding,
        credit: CreditReport | None,
        news: NewsCheck,
        today: date,
    ) -> GradingDecision:
        """Grade an auction.

        Args:
            facts (AuctionFacts): What Investment published about the auction.
            standing (PayerStanding): What the public registries say about the payer.
            credit (CreditReport | None): What a credit bureau reports, if one was asked.
            news (NewsCheck): Negative news found about the payer on the web, if checked.
            today (date): The day of the assessment, to count the days to the due
                date and to tell which sanctions are in force.

        Returns:
            GradingDecision: Eligible with a grade, or rejected with its reason.
        """


class PointsGradingPolicy(RiskGradingPolicy):
    """Grades the payer with points from public registries, a credit bureau and the invoice's term.

    First a filter: a payer missing from the padrón, listed by SUNAT as without
    operating capacity, not active, or whose fiscal address cannot be found
    makes the invoice not eligible. Then points, from a base of 40: being an
    IGV withholding or perception agent, the address condition, company or
    individual, whether the invoice names the payer as SUNAT does, the days
    left to the due date, debt in coactive collection, OECE sanctions, OEFA
    offences, the credit rating and negative news (never more than -30). 75 or
    more is A, 55 or more is B, the rest is C. News never rejects: an automated
    search can mistake a namesake or misread a page. While the padrón has never been loaded, every auction is C, never
    rejected for lack of data; a sanction list never loaded only leaves a note.
    """

    def grade(
        self,
        facts: AuctionFacts,
        standing: PayerStanding,
        credit: CreditReport | None,
        news: NewsCheck,
        today: date,
    ) -> GradingDecision:
        ruc = facts.payer.ruc.value
        if not standing.registry_loaded:
            factor = ScoreFactor(
                "REGISTRY_UNAVAILABLE", 0, "El padrón de SUNAT todavía no está cargado: nota conservadora."
            )
            return self._graded(RiskGrade.C, None, (factor,))

        rejection = self._rejection(ruc, standing)
        if rejection is not None:
            code, reason = rejection
            return GradingDecision(
                eligible=False,
                grade=None,
                score=None,
                factors=(ScoreFactor(code, 0, reason),),
                full_balance_outstanding=True,
                policy_version=POINTS_POLICY_VERSION,
                rejection_code=code,
                rejection_reason=reason,
            )

        factors = [
            *self._agent_factors(standing),
            *self._condition_factors(standing),
            *self._taxpayer_type_factors(ruc),
            *self._name_factors(facts.payer.name, standing.name),
            self._term_factor((facts.due_date - today).days),
            *self._sanction_factors(standing, today),
            *self._credit_factors(credit),
            *self._news_factors(news),
            *self._unavailable_source_factors(standing),
        ]
        score = BASE_SCORE + sum(factor.points for factor in factors)
        return self._graded(grade_for(score), score, tuple(factors))

    @staticmethod
    def _graded(grade: RiskGrade, score: int | None, factors: tuple[ScoreFactor, ...]) -> GradingDecision:
        return GradingDecision(
            eligible=True,
            grade=grade,
            score=score,
            factors=factors,
            full_balance_outstanding=True,
            policy_version=POINTS_POLICY_VERSION,
        )

    @staticmethod
    def _rejection(ruc: str, standing: PayerStanding) -> tuple[str, str] | None:
        if not standing.found:
            return PAYER_NOT_IN_REGISTRY, f"El RUC del pagador ({ruc}) no figura en el padrón de SUNAT."
        if standing.shell_company:
            return (
                PAYER_SHELL_COMPANY,
                "SUNAT declaró al pagador sujeto sin capacidad operativa (SSCO): "
                "sus operaciones no se consideran reales.",
            )
        status = (standing.status or "").strip().upper()
        if status != ACTIVE_STATUS:
            return (
                PAYER_NOT_ACTIVE,
                f"El pagador figura en SUNAT con estado «{status or 'desconocido'}»; "
                "solo se financian pagadores activos.",
            )
        condition = (standing.domicile_condition or "").strip().upper()
        if condition.startswith(NOT_FOUND_CONDITIONS):
            return PAYER_DOMICILE_NOT_FOUND, f"El domicilio fiscal del pagador figura en SUNAT como «{condition}»."
        return None

    @staticmethod
    def _sanction_factors(standing: PayerStanding, today: date) -> list[ScoreFactor]:
        factors = []
        if standing.coactive_debt is not None:
            factors.append(
                ScoreFactor(
                    "COACTIVE_DEBT",
                    -20,
                    f"Tiene deuda en cobranza coactiva con SUNAT por S/ {_soles(standing.coactive_debt)}.",
                )
            )
        if any(period.in_force_on(today) for period in standing.oece_disqualifications):
            factors.append(
                ScoreFactor("OECE_DISQUALIFIED", -15, "Está inhabilitado por OECE para contratar con el Estado.")
            )
        if standing.oece_fines:
            total = sum((period.amount or Decimal(0) for period in standing.oece_fines), Decimal(0))
            factors.append(
                ScoreFactor(
                    "OECE_UNPAID_FINE",
                    -10,
                    f"Tiene {len(standing.oece_fines)} multa(s) de OECE sin pagar por S/ {_soles(total)}.",
                )
            )
        if standing.environmental_infractions > 0:
            factors.append(
                ScoreFactor(
                    "ENVIRONMENTAL_OFFENDER",
                    -5,
                    f"Figura en el registro de infractores ambientales de OEFA "
                    f"({standing.environmental_infractions} infracciones).",
                )
            )
        return factors

    @staticmethod
    def _credit_factors(credit: CreditReport | None) -> list[ScoreFactor]:
        if credit is None:
            return []
        code, points, label = CREDIT_RATING_POINTS[credit.rating]
        source = "central de riesgos (simulado)" if credit.simulated else f"central de riesgos ({credit.source})"
        return [ScoreFactor(code, points, f"Calificación SBS «{label}» según la {source}.")]

    @staticmethod
    def _news_factors(news: NewsCheck) -> list[ScoreFactor]:
        if news.status is NewsCheckStatus.NOT_SCREENED:
            return [ScoreFactor("NEWS_NOT_SCREENED", 0, "No se buscaron noticias del pagador: búsqueda apagada.")]
        if news.status is NewsCheckStatus.UNAVAILABLE or news.screening is None:
            return [ScoreFactor("NEWS_UNAVAILABLE", 0, "La búsqueda de noticias del pagador no respondió.")]
        serious = [f for f in news.screening.findings if f.severity is NewsSeverity.SERIOUS]
        moderate = [f for f in news.screening.findings if f.severity is NewsSeverity.MODERATE]
        factors = []
        if serious:
            factors.append(ScoreFactor("NEGATIVE_NEWS_SERIOUS", NEWS_SERIOUS_POINTS, _headlines(serious)))
        if moderate:
            factors.append(ScoreFactor("NEGATIVE_NEWS_MODERATE", NEWS_MODERATE_POINTS, _headlines(moderate)))
        return factors

    @staticmethod
    def _unavailable_source_factors(standing: PayerStanding) -> list[ScoreFactor]:
        return [
            ScoreFactor(
                "SOURCE_UNAVAILABLE", 0, f"No se consultó la {SOURCE_NAMES.get(source, source)}: no está cargada."
            )
            for source in standing.unavailable_sources
        ]

    @staticmethod
    def _agent_factors(standing: PayerStanding) -> list[ScoreFactor]:
        if standing.withholding_agent:
            return [ScoreFactor("WITHHOLDING_AGENT", 20, "SUNAT lo designó agente de retención del IGV.")]
        if standing.perception_agent:
            return [ScoreFactor("PERCEPTION_AGENT", 10, "SUNAT lo designó agente de percepción del IGV.")]
        return []

    @staticmethod
    def _condition_factors(standing: PayerStanding) -> list[ScoreFactor]:
        condition = (standing.domicile_condition or "").strip().upper()
        if condition == FOUND_CONDITION:
            return [ScoreFactor("DOMICILE_FOUND", 10, "Domicilio fiscal HABIDO en SUNAT.")]
        if condition.startswith(UNVERIFIED_CONDITIONS):
            return [ScoreFactor("DOMICILE_UNVERIFIED", -10, f"Domicilio fiscal «{condition}» en SUNAT.")]
        return []

    @staticmethod
    def _taxpayer_type_factors(ruc: str) -> list[ScoreFactor]:
        if ruc.startswith("20"):
            return [ScoreFactor("COMPANY", 5, "El pagador es una persona jurídica (RUC 20).")]
        if ruc.startswith("10"):
            return [ScoreFactor("INDIVIDUAL", -5, "El pagador es una persona natural con negocio (RUC 10).")]
        return []

    @staticmethod
    def _name_factors(invoice_name: str, registered_name: str | None) -> list[ScoreFactor]:
        if not registered_name:
            return []
        if names_match(invoice_name, registered_name):
            return [ScoreFactor("NAME_MATCHES", 5, "La razón social de la factura coincide con la de SUNAT.")]
        return [
            ScoreFactor(
                "NAME_MISMATCH",
                -15,
                f"La factura nombra al pagador «{invoice_name}», pero SUNAT lo registra como «{registered_name}».",
            )
        ]

    @staticmethod
    def _term_factor(days: int) -> ScoreFactor:
        if days <= 30:
            return ScoreFactor("TERM_UP_TO_30_DAYS", 10, f"Vence en {days} días.")
        if days <= 60:
            return ScoreFactor("TERM_31_TO_60_DAYS", 5, f"Vence en {days} días.")
        if days <= 90:
            return ScoreFactor("TERM_61_TO_90_DAYS", 0, f"Vence en {days} días.")
        return ScoreFactor("TERM_OVER_90_DAYS", -10, f"Vence en {days} días.")


def _headlines(findings: list[NewsFinding]) -> str:
    shown = "; ".join(f"«{f.headline}» ({f.url})" for f in findings[:NEWS_HEADLINES_SHOWN])
    more = f" y {len(findings) - NEWS_HEADLINES_SHOWN} más" if len(findings) > NEWS_HEADLINES_SHOWN else ""
    return f"Según búsqueda automática (IA): {shown}{more}."


def _soles(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def grade_for(score: int) -> RiskGrade:
    """Turn a score into a grade: 75 or more is A, 55 or more is B, the rest is C."""
    if score >= GRADE_A_FROM:
        return RiskGrade.A
    if score >= GRADE_B_FROM:
        return RiskGrade.B
    return RiskGrade.C


def normalize_company_name(name: str) -> str:
    """Write a company name the same way however it was typed.

    Upper case, no accents, no punctuation, and no legal-form suffix, so that
    ``Pagador S.A.C.`` and ``PAGADOR SOCIEDAD ANONIMA CERRADA`` both become ``PAGADOR``.
    """
    text = "".join(c for c in unicodedata.normalize("NFKD", name.upper()) if not unicodedata.combining(c))
    for form in _LEGAL_FORMS:
        text = text.replace(form, " ")
    text = text.replace(".", "")
    tokens = re.sub(r"[^A-Z0-9Ñ]+", " ", text).split()
    return " ".join(token for token in tokens if token not in _LEGAL_FORM_TOKENS)


def names_match(invoice_name: str, registered_name: str) -> bool:
    """Tell whether two names are the same company, allowing for small differences."""
    left, right = normalize_company_name(invoice_name), normalize_company_name(registered_name)
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= NAME_MATCH_THRESHOLD
