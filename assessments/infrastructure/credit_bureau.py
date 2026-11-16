"""Credit bureau adapters.

SIMULATED. Vankoo has no contract with a credit bureau (Equifax/Infocorp,
Sentinel…), and a crowdfunding platform supervised by the SMV has no direct
access to the SBS's Reporte Crediticio Consolidado. ``SimulatedCreditBureau``
stands in for the bureau a real Vankoo would hire: it makes up an SBS rating
from the RUC, always the same for the same RUC, so the scoring has the signal
it would have in production. Every report it gives says ``simulated``, and so
does every factor built from it. Replacing it means writing an adapter for the
real bureau's API and choosing it in ``assessments/interfaces/dependencies.py``.
"""
import hashlib

from assessments.application.outbound_services import CreditBureau
from assessments.domain.value_objects import CreditReport, Ruc, SbsRating

SIMULATED_SOURCE = "simulated-bureau-v1"

# How often each rating comes out, in hundredths. Roughly the spread of Peru's
# business credit portfolio, with most debtors rated Normal.
RATING_SHARES: tuple[tuple[SbsRating, int], ...] = (
    (SbsRating.NORMAL, 70),
    (SbsRating.POTENTIAL_PROBLEMS, 12),
    (SbsRating.DEFICIENT, 8),
    (SbsRating.DOUBTFUL, 6),
    (SbsRating.LOSS, 4),
)


class SimulatedCreditBureau(CreditBureau):
    """SIMULATED bureau: an SBS rating derived from the RUC's hash, stable for each RUC."""

    async def report(self, ruc: Ruc) -> CreditReport | None:
        return CreditReport(rating=simulated_rating(ruc.value), source=SIMULATED_SOURCE, simulated=True)


class DisabledCreditBureau(CreditBureau):
    """No bureau at all: the scoring leaves the credit rating out."""

    async def report(self, ruc: Ruc) -> CreditReport | None:
        return None


def simulated_rating(ruc: str) -> SbsRating:
    """The rating the simulated bureau gives a RUC: the same every time."""
    bucket = int.from_bytes(hashlib.sha256(ruc.encode()).digest()[:8], "big") % 100
    for rating, share in RATING_SHARES:
        if bucket < share:
            return rating
        bucket -= share
    return SbsRating.NORMAL
