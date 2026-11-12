"""What the Assessments context asks the Registries and Sustainability contexts.

The only module of Assessments that imports them: it asks their facades with
primitives and answers in Assessments' own terms.
"""
from datetime import date

from assessments.domain.value_objects import (
    GreenCertificate,
    GreenCheck,
    GreenCriterion,
    GreenStatus,
    PayerStanding,
    Ruc,
    SanctionPeriod,
)
from registries.interfaces.acl import RegistriesContextFacade, SanctionPeriodRecord
from sustainability.interfaces.acl import SustainabilityContextFacade

WITHHOLDING = "WITHHOLDING"
PERCEPTION_ROLES = frozenset({"PERCEPTION_DOMESTIC_SALES", "PERCEPTION_FUEL"})


class ExternalRegistriesService:
    """What Assessments needs to know about a payer from the public registries."""

    def __init__(self, registries_facade: RegistriesContextFacade) -> None:
        """Initialize the service on the registries' facade.

        Args:
            registries_facade (RegistriesContextFacade): Answers on the caller's session.
        """
        self._registries = registries_facade

    async def payer_standing(self, ruc: Ruc) -> PayerStanding:
        """Tell what the public registries say about the payer of an invoice."""
        record = await self._registries.payer_standing(ruc.value)
        return PayerStanding(
            registry_loaded=record.registry_loaded,
            found=record.found,
            name=record.name,
            status=record.status,
            domicile_condition=record.domicile_condition,
            ubigeo=record.ubigeo,
            withholding_agent=WITHHOLDING in record.agent_types,
            perception_agent=bool(PERCEPTION_ROLES.intersection(record.agent_types)),
            shell_company=record.shell_company,
            coactive_debt=record.coactive_debt,
            oece_disqualifications=_periods(record.oece_disqualifications),
            oece_fines=_periods(record.oece_fines),
            environmental_infractions=record.environmental_infractions,
            unavailable_sources=record.unavailable_sources,
        )


def _periods(records: tuple[SanctionPeriodRecord, ...]) -> tuple[SanctionPeriod, ...]:
    return tuple(SanctionPeriod(record.starts_on, record.ends_on, record.amount) for record in records)


class ExternalSustainabilityService:
    """Whether the MYPE behind an auction is green."""

    def __init__(self, sustainability_facade: SustainabilityContextFacade) -> None:
        """Initialize the service on the Sustainability facade.

        Args:
            sustainability_facade (SustainabilityContextFacade): Answers on the caller's session.
        """
        self._sustainability = sustainability_facade

    async def green_check(self, mype_id: str, today: date) -> GreenCheck:
        """Tell whether a MYPE is green on a day, with the certificate when it is.

        Args:
            mype_id (str): The MYPE that sells the invoice.
            today (date): The day of the assessment, in Lima.
        """
        record = await self._sustainability.green_status(mype_id, today)
        status = GreenStatus(record.status)
        if status is not GreenStatus.GREEN:
            return GreenCheck(status)
        certification_id, standard, issuer, valid_until = (
            record.certification_id,
            record.standard,
            record.issuer,
            record.valid_until,
        )
        if certification_id is None or standard is None or issuer is None or valid_until is None:
            # Sustainability never answers GREEN without them; treat a gap as not green.
            return GreenCheck(GreenStatus.NOT_GREEN)
        return GreenCheck(
            status,
            GreenCertificate(
                certification_id=certification_id,
                standard=standard,
                issuer=issuer,
                valid_until=valid_until,
                criteria=tuple(GreenCriterion(item.code, item.detail) for item in record.criteria if item.passed),
            ),
        )
