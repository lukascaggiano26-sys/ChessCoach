from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class EngineLine:
    multipv: int
    move_uci: str
    move_san: str
    score_cp: int
    pv_uci: list[str] = field(default_factory=list)
    pv_san: list[str] = field(default_factory=list)


@dataclass
class PositionAnalysis:
    ply: int
    side: str
    fen: str
    eval_before_cp: int
    eval_after_played_cp: int
    eval_after_best_cp: int
    lines: list[EngineLine] = field(default_factory=list)


@dataclass
class MoveReview:
    san: str
    uci: str
    ply: int
    side: str
    label: str
    expected_points_before: float
    expected_points_after_best: float
    expected_points_after_played: float
    expected_points_loss: float
    best_move_uci: str
    best_move_san: str
    best_pv: list[str]
    played_pv: list[str]
    tactical_tags: list[str]
    short_explanation: str
    detailed_explanation: str
    move_number: int
    move_number_display: str
    classification_reason: str
    eval_before_cp: int
    eval_after_cp: int
    best_eval_after_cp: int
    label_evidence: dict[str, Any] = field(default_factory=dict)
    engine_metadata: dict[str, Any] = field(default_factory=dict)
    fen_before: str = ""
    fen_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GameReview:
    url: str | None
    time_class: str | None
    rated: bool | None
    end_time: int | None
    player_color: str
    player_result: str
    opening: str
    stage_performance: dict[str, dict[str, Any]]
    engine_version: str | None
    engine_warning: str | None
    engine_depth: int | None
    average_eval_delta_cp: float | None
    engine_metadata: dict[str, Any] = field(default_factory=dict)
    move_quality_counts: dict[str, int] = field(default_factory=dict)
    key_moments: list[dict[str, Any]] = field(default_factory=list)
    best_missed_opportunities: list[dict[str, Any]] = field(default_factory=list)
    tactical_themes: dict[str, int] = field(default_factory=dict)
    reviewed_moves: list[MoveReview] = field(default_factory=list)
    good_moves: list[dict[str, Any]] = field(default_factory=list)
    bad_moves: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reviewed_moves"] = [m.to_dict() for m in self.reviewed_moves]
        return payload
