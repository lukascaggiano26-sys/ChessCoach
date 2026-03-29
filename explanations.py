from __future__ import annotations

from typing import Literal

GameState = Literal["winning", "equal", "losing"]


def score_to_state(expected_points: float) -> GameState:
    if expected_points >= 0.67:
        return "winning"
    if expected_points <= 0.33:
        return "losing"
    return "equal"


def describe_transition(before: float, after: float) -> str | None:
    b = score_to_state(before)
    a = score_to_state(after)
    if b == a:
        return None
    return f"{b} -> {a}"


def classify_issue_type(label: str, tags: list[str], delta_cp: int, phase: str) -> str:
    if label == "Miss":
        return "missed defensive resource"
    if any(t in tags for t in ["mate threat", "back-rank tactic", "discovered check"]):
        return "king safety"
    if any(t in tags for t in ["fork", "pin", "skewer", "double attack", "zwischenzug"]):
        return "immediate tactic"
    if delta_cp <= -150:
        return "material loss"
    if phase == "endgame" and label in {"Inaccuracy", "Mistake", "Blunder"}:
        return "endgame conversion"
    return "strategic inaccuracy"


def _tag_phrase(tags: list[str]) -> str | None:
    if not tags:
        return None
    preferred = [
        "fork",
        "pin",
        "skewer",
        "discovered attack",
        "discovered check",
        "removal of defender",
        "deflection",
        "decoy",
        "interference",
        "overload",
        "clearance",
        "back-rank tactic",
        "zwischenzug",
        "promotion tactic",
        "exchange sacrifice",
        "mate threat",
        "hanging piece",
    ]
    for p in preferred:
        if p in tags:
            return p
    return tags[0]


def build_short_explanation(
    label: str,
    best_move_san: str,
    *,
    played_san: str | None = None,
    tags: list[str] | None = None,
    transition: str | None = None,
    issue_type: str | None = None,
) -> str:
    tags = tags or []
    motif = _tag_phrase(tags)

    if label == "Best":
        if motif:
            return f"Best move: {played_san or 'This move'} exploits a {motif}."
        return "Best move: it matches the top engine continuation."

    base = f"{label}: best move was {best_move_san}."
    extras: list[str] = []
    if motif:
        extras.append(f"Key motif: {motif}")
    if transition:
        extras.append(f"State change: {transition}")
    if issue_type:
        extras.append(f"Issue: {issue_type}")
    if extras:
        return base + " " + "; ".join(extras) + "."
    return base


def build_detailed_explanation(
    label: str,
    best_move_san: str,
    ep_loss: float,
    delta_cp: int,
    tags: list[str],
    *,
    played_san: str | None = None,
    transition: str | None = None,
    issue_type: str | None = None,
    phase: str = "middlegame",
) -> str:
    motif = _tag_phrase(tags)
    issue = issue_type or classify_issue_type(label, tags, delta_cp, phase)
    played = played_san or "the played move"

    s1 = f"{label}: you played {played}, while the engine prefers {best_move_san}."

    if motif:
        if motif == "fork":
            s2 = "This allowed a fork pattern that created immediate tactical pressure."
        elif motif == "removal of defender":
            s2 = "This removed the defender of a critical square and changed tactical balance."
        elif motif == "exchange sacrifice":
            s2 = "This involved an exchange sacrifice motif that required precise follow-up."
        else:
            s2 = f"The key tactical/strategic reason was {motif}."
    else:
        s2 = "The main difference was positional quality rather than a single forcing tactic."

    s3 = f"Expected-points loss was {ep_loss:.3f} and the evaluation swing was {delta_cp:+} centipawns."

    if transition:
        s4 = f"Game-state transition: {transition}."
    else:
        s4 = "Game state stayed in the same broad bucket, but move quality still mattered."

    s5 = f"Primary issue type: {issue}."

    return " ".join([s1, s2, s3, s4, s5])
