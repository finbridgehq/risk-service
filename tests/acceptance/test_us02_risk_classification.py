"""US02: la clasificación de riesgo mira al pagador, no a la MYPE."""

from datetime import date
from typing import Any, cast

from assessments.application.acl import ExternalRegistriesService
from assessments.domain.services import (
    PAYER_NOT_IN_REGISTRY,
    PAYER_SHELL_COMPANY,
    PointsGradingPolicy,
)
from assessments.domain.value_objects import GradingDecision, NewsCheck, NewsCheckStatus, Ruc
from registries.interfaces.acl import PayerStandingRecord
from tests.fakes import ACTIVE_COMPANY, FakeRegistriesFacade, FixedCreditBureau, facts

TODAY = date(2026, 10, 14)
PAYER = Ruc("20123456789")
NO_NEWS = NewsCheck(NewsCheckStatus.NOT_SCREENED)


async def grade(standing: PayerStandingRecord) -> GradingDecision:
    registries = FakeRegistriesFacade(standing)
    bureau = FixedCreditBureau()
    payer = await ExternalRegistriesService(cast(Any, registries)).payer_standing(PAYER)
    credit = await bureau.report(PAYER)
    return PointsGradingPolicy().grade(facts(), payer, credit, NO_NEWS, TODAY)


async def test_an_active_registered_payer_receives_a_grade_with_its_factors() -> None:
    # Dado un pagador activo y habido en el padrón de SUNAT
    # Cuando se califica la factura
    decision = await grade(ACTIVE_COMPANY)

    # Entonces recibe una calificación y los factores que la explican
    assert decision.eligible is True
    assert decision.grade is not None
    assert decision.factors


async def test_a_payer_missing_from_the_registry_is_not_eligible() -> None:
    # Dado un pagador que no figura en el padrón
    missing = PayerStandingRecord(
        registry_loaded=True,
        found=False,
        name=None,
        status=None,
        domicile_condition=None,
    )

    # Cuando se califica la factura
    decision = await grade(missing)

    # Entonces la operación no es elegible y el motivo es PAYER_NOT_IN_REGISTRY
    assert decision.eligible is False
    assert decision.grade is None
    assert decision.rejection_code == PAYER_NOT_IN_REGISTRY


async def test_a_shell_company_is_not_eligible() -> None:
    # Dado un pagador que SUNAT declaró sujeto sin capacidad operativa
    shell = PayerStandingRecord(
        registry_loaded=True,
        found=True,
        name=ACTIVE_COMPANY.name,
        status="ACTIVO",
        domicile_condition="HABIDO",
        shell_company=True,
    )

    # Cuando se califica la factura
    decision = await grade(shell)

    # Entonces la operación no es elegible y el motivo es PAYER_SHELL_COMPANY
    assert decision.eligible is False
    assert decision.grade is None
    assert decision.rejection_code == PAYER_SHELL_COMPANY
