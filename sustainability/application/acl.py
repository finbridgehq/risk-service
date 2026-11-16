"""What the Sustainability context asks the Registries context.

The only module of Sustainability that imports Registries.
"""
from registries.interfaces.acl import RegistriesContextFacade
from sustainability.domain.value_objects import CompanyStanding, Ruc

ENVIRONMENTAL_REGISTRY = "oefa-ruias"


class ExternalRegistriesService:
    """What the green rules need to know about a MYPE's RUC."""

    def __init__(self, registries_facade: RegistriesContextFacade) -> None:
        """Initialize the service on the registries' facade.

        Args:
            registries_facade (RegistriesContextFacade): Answers on the caller's session.
        """
        self._registries = registries_facade

    async def company_standing(self, ruc: Ruc) -> CompanyStanding:
        """Tell the name SUNAT has for the RUC and whether OEFA lists it."""
        record = await self._registries.payer_standing(ruc.value)
        return CompanyStanding(
            registry_loaded=record.registry_loaded,
            registered_name=record.name if record.found else None,
            environmental_registry_loaded=record.registry_loaded
            and ENVIRONMENTAL_REGISTRY not in record.unavailable_sources,
            environmental_infractions=record.environmental_infractions,
        )
