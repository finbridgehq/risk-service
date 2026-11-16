"""What other bounded contexts may ask the Sustainability context.

Primitives in, primitives out: Assessments asks, for each auction, whether its
MYPE is green on that day, and gets the certificate and the checks behind the
answer without seeing this context's model.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from registries.interfaces.acl import RegistriesContextFacade
from sustainability.application.acl import ExternalRegistriesService
from sustainability.application.services import GreenCertificationQueryService
from sustainability.infrastructure.repositories import SqlAlchemyGreenCertificationRepository


@dataclass(frozen=True, slots=True, kw_only=True)
class GreenCriterionRecord:
    """One check of the rules.

    Attributes:
        code (str): Which check, e.g. ``IN_FORCE``.
        passed (bool): Whether it passed.
        detail (str): What was found, in Spanish.
    """

    code: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GreenStatusRecord:
    """Whether a MYPE is green on a given day.

    Attributes:
        status (str): ``GREEN``, or why not: ``NO_CERTIFICATE``, ``NOT_GREEN``,
            ``EXPIRED`` or ``ENVIRONMENTAL_OFFENDER``.
        certification_id (str | None): Its latest decided certificate.
        standard (str | None): ``ISO_14001`` or ``ISO_50001``.
        issuer (str | None): The certification body.
        valid_until (date | None): When the certificate expires.
        criteria (tuple[GreenCriterionRecord, ...]): The checks it was decided on.
    """

    status: str
    certification_id: str | None = None
    standard: str | None = None
    issuer: str | None = None
    valid_until: date | None = None
    criteria: tuple[GreenCriterionRecord, ...] = ()


class SustainabilityContextFacade:
    """What other bounded contexts may ask the Sustainability context."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the facade on the caller's session.

        Args:
            session (AsyncSession): The caller's session.
        """
        self._queries = GreenCertificationQueryService(
            SqlAlchemyGreenCertificationRepository(session),
            ExternalRegistriesService(RegistriesContextFacade(session)),
        )

    async def green_status(self, mype_user_id: str, today: date) -> GreenStatusRecord:
        """Tell whether a MYPE is green on a day.

        Args:
            mype_user_id (str): The MYPE's IAM account, the ``mypeId`` of its auctions.
            today (date): The day being asked about, in Lima.

        Returns:
            GreenStatusRecord: The answer, with the certificate behind it.
        """
        status = await self._queries.get_green_status(mype_user_id, today)
        certification = status.certification
        if certification is None:
            return GreenStatusRecord(status=status.code.value)
        return GreenStatusRecord(
            status=status.code.value,
            certification_id=certification.certification_id.value,
            standard=certification.standard.value if certification.standard else None,
            issuer=certification.issuer,
            valid_until=certification.valid_until,
            criteria=tuple(
                GreenCriterionRecord(code=result.code.value, passed=result.passed, detail=result.detail)
                for result in certification.criteria
            ),
        )
