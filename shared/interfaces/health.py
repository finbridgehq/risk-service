"""Health endpoints for the container orchestrator.

``/health`` answers whenever the process is up (liveness). ``/health/ready``
also checks the database and every check the application registered in
``app.state.readiness_checks`` (the Kafka consumer, the delivery worker), and
answers 503 if any of them is down. Both sit outside ``/api/v1``: they are for
Docker and Azure, not for API clients.
"""
from collections.abc import Callable

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.interfaces.dependencies import SessionDep

router = APIRouter(prefix="/health", tags=["Health"])

type ReadinessCheck = Callable[[], bool]


class HealthResponse(BaseModel):
    """Whether the service is up, and each check that decided it.

    Attributes:
        status (str): ``UP`` or ``DOWN``.
        checks (dict[str, bool]): Each dependency checked, and whether it is up.
    """

    status: str
    checks: dict[str, bool] = {}


@router.get("")
async def get_liveness() -> HealthResponse:
    """Answer while the process is running."""
    return HealthResponse(status="UP")


@router.get("/ready", responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}})
async def get_readiness(request: Request, response: Response, session: SessionDep) -> HealthResponse:
    """Answer 200 only when the database and every background task are up."""
    checks = {"database": await _database_is_up(session)}
    registered: dict[str, ReadinessCheck] = getattr(request.app.state, "readiness_checks", {})
    checks.update({name: check() for name, check in registered.items()})
    if all(checks.values()):
        return HealthResponse(status="UP", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="DOWN", checks=checks)


async def _database_is_up(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
