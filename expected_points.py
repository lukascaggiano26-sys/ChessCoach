from __future__ import annotations

from typing import Any


def _score_to_cp_fallback(score: Any) -> int:
    """Fallback conversion when WDL is unavailable."""
    if hasattr(score, "score"):
        return int(score.score(mate_score=100000))
    if isinstance(score, (int, float)):
        return int(score)
    raise TypeError(f"Unsupported score type: {type(score)!r}")


def score_to_expected_points(score: Any, ply: int, rating_bucket: str | None = None) -> float:
    """Convert a python-chess score object into expected points in [0, 1].

    Faithful to public Chess.com behavior (high level):
    - Uses engine evaluation to estimate expected points.
    - Mate scores dominate centipawn scores naturally.

    Implementation inference:
    - Uses python-chess WDL conversion (`score.wdl`) as the expectation backbone.
    - `rating_bucket` is currently reserved for future calibration and is not yet applied.
    """
    del rating_bucket  # reserved extension point

    # Preferred path: python-chess score semantics -> WDL expectation.
    if hasattr(score, "wdl"):
        wdl = score.wdl(model="sf", ply=max(1, int(ply)))
        total = wdl.total()
        if total > 0:
            return max(0.0, min(1.0, (wdl.wins + 0.5 * wdl.draws) / total))

    # Fallback path for non-score inputs.
    cp = _score_to_cp_fallback(score)
    expectation = 1.0 / (1.0 + 10 ** (-cp / 360.0))
    return max(0.0, min(1.0, expectation))


def expected_points_loss(best_score: Any, played_score: Any, ply: int, rating_bucket: str | None = None) -> float:
    """Expected points lost by playing `played_score` instead of `best_score`."""
    best = score_to_expected_points(best_score, ply=ply, rating_bucket=rating_bucket)
    played = score_to_expected_points(played_score, ply=ply, rating_bucket=rating_bucket)
    return max(0.0, best - played)


# Backward-compatible helper retained for existing call sites/tests.
def expected_points_from_cp(eval_cp: int, rating: int) -> float:
    del rating
    return score_to_expected_points(eval_cp, ply=20)
