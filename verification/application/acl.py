"""What the Verification context asks the Registries context.

The only module of Verification that imports Registries.
"""
from datetime import date

from registries.interfaces.acl import RegistriesContextFacade, SanctionPeriodRecord
from verification.domain.value_objects import Ruc, TaxpayerStanding

SHELL_COMPANIES = "sunat-ssco"


class ExternalRegistriesService:
    """What the KYC rules need to know about a MYPE's RUC."""

    def __init__(self, registries_facade: RegistriesContextFacade) -> None:
        """Initialize the service on the registries' facade.

        Args:
            registries_facade (RegistriesContextFacade): Answers on the caller's session.
        """
        self._registries = registries_facade

    async def taxpayer_standing(self, ruc: Ruc, today: date) -> TaxpayerStanding:
        """Tell what SUNAT's padrón and the sanction lists say about the RUC today.

        Args:
            ruc (Ruc): The declared RUC.
            today (date): The day OECE's disqualifications are counted on, in Lima.
        """
        record = await self._registries.payer_standing(ruc.value)
        return TaxpayerStanding(
            registry_loaded=record.registry_loaded,
            shell_registry_loaded=record.registry_loaded and SHELL_COMPANIES not in record.unavailable_sources,
            found=record.found,
            registered_name=record.name,
            status=record.status,
            domicile_condition=record.domicile_condition,
            shell_company=record.shell_company,
            coactive_debt=record.coactive_debt,
            oece_sanctions=sum(1 for period in record.oece_disqualifications if _in_force(period, today))
            + len(record.oece_fines),
            environmental_infractions=record.environmental_infractions,
        )


def _in_force(period: SanctionPeriodRecord, today: date) -> bool:
    started = period.starts_on is None or period.starts_on <= today
    return started and (period.ends_on is None or period.ends_on >= today)
