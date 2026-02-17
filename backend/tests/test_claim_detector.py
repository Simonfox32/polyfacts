"""Tests for the claim worthiness heuristic scorer."""

import pytest

from app.services.claim_detector import ClaimDetector


@pytest.fixture
def detector():
    return ClaimDetector()


class TestClaimWorthiness:
    async def test_numeric_claim_scores_high(self, detector):
        score = await detector.score_claim_worthiness(
            "The unemployment rate is at 3.4 percent, a fifty-year low."
        )
        assert score >= 0.4

    async def test_policy_claim_scores_high(self, detector):
        score = await detector.score_claim_worthiness(
            "Congress passed a two trillion dollar infrastructure bill last year."
        )
        assert score >= 0.4

    async def test_opinion_scores_low(self, detector):
        score = await detector.score_claim_worthiness(
            "I think we should invest more in education."
        )
        assert score <= 0.3

    async def test_short_sentence_scores_low(self, detector):
        score = await detector.score_claim_worthiness("Thank you.")
        assert score <= 0.1

    async def test_statistical_language(self, detector):
        score = await detector.score_claim_worthiness(
            "Crime rates have decreased by 15 percent in major cities since 2020."
        )
        assert score >= 0.4
