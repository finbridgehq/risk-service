"""The simulated credit bureau: stable per RUC, spread like a real portfolio, and marked simulated."""
from collections import Counter

from assessments.domain.value_objects import Ruc, SbsRating
from assessments.infrastructure.credit_bureau import DisabledCreditBureau, SimulatedCreditBureau, simulated_rating


async def test_the_same_ruc_always_gets_the_same_simulated_rating() -> None:
    bureau = SimulatedCreditBureau()
    first = await bureau.report(Ruc("20100002621"))
    second = await bureau.report(Ruc("20100002621"))
    assert first == second
    assert first is not None and first.simulated is True and first.source == "simulated-bureau-v1"


def test_ratings_spread_like_the_published_shares() -> None:
    counts = Counter(simulated_rating(f"20{n:09d}") for n in range(20_000))
    shares = {rating: counts[rating] / 20_000 for rating in SbsRating}
    assert 0.66 < shares[SbsRating.NORMAL] < 0.74
    assert 0.02 < shares[SbsRating.LOSS] < 0.06
    assert set(counts) == set(SbsRating)


async def test_a_disabled_bureau_reports_nothing() -> None:
    assert await DisabledCreditBureau().report(Ruc("20100002621")) is None
