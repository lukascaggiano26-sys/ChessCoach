from __future__ import annotations

from typing import Any

ORDINARY_BANDS = {
    "Best": (0.0, 0.0),
    "Excellent": (0.0, 0.02),
    "Good": (0.02, 0.05),
    "Inaccuracy": (0.05, 0.10),
    "Mistake": (0.10, 0.20),
    "Blunder": (0.20, 1.00),
}


def classify_expected_points_loss(loss: float) -> str:
    """Ordinary-label classifier using exact required EP-loss bands."""
    loss = max(0.0, min(1.0, float(loss)))
    if loss == 0.0:
        return "Best"
    if 0.0 < loss <= 0.02:
        return "Excellent"
    if 0.02 < loss <= 0.05:
        return "Good"
    if 0.05 < loss <= 0.10:
        return "Inaccuracy"
    if 0.10 < loss <= 0.20:
        return "Mistake"
    return "Blunder"


def _brilliant_allowed(
    *,
    near_best: bool,
    sound_sacrifice: bool,
    trivially_winning_before: bool,
    obvious_recapture: bool,
    phase: str,
) -> bool:
    if not near_best:
        return False
    if not sound_sacrifice:
        return False
    if trivially_winning_before:
        return False
    if obvious_recapture:
        return False
    # Stricter bar in endgames.
    if phase == "endgame" and not sound_sacrifice:
        return False
    return True


def _great_allowed(
    *,
    near_best: bool,
    only_move_save: bool,
    only_move_equalize: bool,
    punished_opponent_error: bool,
) -> bool:
    if not near_best:
        return False
    return only_move_save or only_move_equalize or punished_opponent_error


def _miss_allowed(
    *,
    missed_forced_mate: bool,
    missed_large_material_win: bool,
    missed_clear_equalization: bool,
    missed_transition_to_winning: bool,
) -> bool:
    return (
        missed_forced_mate
        or missed_large_material_win
        or missed_clear_equalization
        or missed_transition_to_winning
    )


def assign_move_label(
    *,
    expected_points_loss: float,
    is_book: bool = False,
    near_best: bool = False,
    phase: str = "middlegame",
    sound_sacrifice: bool = False,
    trivially_winning_before: bool = False,
    obvious_recapture: bool = False,
    only_move_save: bool = False,
    only_move_equalize: bool = False,
    punished_opponent_error: bool = False,
    missed_forced_mate: bool = False,
    missed_large_material_win: bool = False,
    missed_clear_equalization: bool = False,
    missed_transition_to_winning: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Assign Chess.com-style move label with precedence + evidence.

    Precedence: Book > Brilliant > Great > Miss > ordinary EP-loss label.
    """
    ordinary = classify_expected_points_loss(expected_points_loss)
    evidence: dict[str, Any] = {
        "ep_loss": float(max(0.0, min(1.0, expected_points_loss))),
        "ordinary_label": ordinary,
        "precedence": ["Book", "Brilliant", "Great", "Miss", "ordinary"],
        "flags": {
            "is_book": is_book,
            "near_best": near_best,
            "phase": phase,
            "sound_sacrifice": sound_sacrifice,
            "trivially_winning_before": trivially_winning_before,
            "obvious_recapture": obvious_recapture,
            "only_move_save": only_move_save,
            "only_move_equalize": only_move_equalize,
            "punished_opponent_error": punished_opponent_error,
            "missed_forced_mate": missed_forced_mate,
            "missed_large_material_win": missed_large_material_win,
            "missed_clear_equalization": missed_clear_equalization,
            "missed_transition_to_winning": missed_transition_to_winning,
        },
        "band": ORDINARY_BANDS[ordinary],
    }

    if is_book:
        evidence["trigger"] = "opening_book"
        return "Book", evidence

    if _brilliant_allowed(
        near_best=near_best,
        sound_sacrifice=sound_sacrifice,
        trivially_winning_before=trivially_winning_before,
        obvious_recapture=obvious_recapture,
        phase=phase,
    ):
        evidence["trigger"] = "sound_near_best_sacrifice"
        return "Brilliant", evidence

    if _great_allowed(
        near_best=near_best,
        only_move_save=only_move_save,
        only_move_equalize=only_move_equalize,
        punished_opponent_error=punished_opponent_error,
    ):
        evidence["trigger"] = "near_best_state_change"
        return "Great", evidence

    if _miss_allowed(
        missed_forced_mate=missed_forced_mate,
        missed_large_material_win=missed_large_material_win,
        missed_clear_equalization=missed_clear_equalization,
        missed_transition_to_winning=missed_transition_to_winning,
    ):
        evidence["trigger"] = "missed_opportunity"
        return "Miss", evidence

    evidence["trigger"] = "ordinary_ep_band"
    return ordinary, evidence


# Backward-compatible helper retained for older call sites.
def apply_special_labels(base_label: str, eval_before: int, eval_after: int, expected_best: float, is_sacrifice: bool) -> str:
    near_best = base_label in {"Best", "Excellent", "Good"}
    label, _ = assign_move_label(
        expected_points_loss=0.0 if base_label == "Best" else 0.03,
        near_best=near_best,
        sound_sacrifice=is_sacrifice,
        trivially_winning_before=eval_before >= 600,
        only_move_save=(eval_after - eval_before) >= 180,
        only_move_equalize=(eval_before < -80 and eval_after >= -20),
        punished_opponent_error=expected_best >= 0.75,
    )
    if label in {"Book", "Brilliant", "Great", "Miss"}:
        return label
    return base_label
