from __future__ import annotations

import importlib
import importlib.util
import io
import sys
from typing import Any

from classify import assign_move_label
from expected_points import expected_points_loss, score_to_expected_points
from explanations import (
    build_detailed_explanation,
    build_short_explanation,
    classify_issue_type,
    describe_transition,
)
from models import EngineLine, GameReview, MoveReview
from motifs import detect_tactical_tags


def _load_python_chess() -> tuple[Any, Any, Any]:
    if importlib.util.find_spec("chess") is None:
        raise RuntimeError(
            "python-chess is required for engine analysis. "
            f"Install it for this interpreter with: {sys.executable} -m pip install python-chess"
        )
    chess = importlib.import_module("chess")
    chess_pgn = importlib.import_module("chess.pgn")
    chess_engine = importlib.import_module("chess.engine")
    return chess, chess_pgn, chess_engine


def get_player_color(game: dict[str, Any], username: str) -> str | None:
    white_name = str(game.get("white", {}).get("username", "")).lower()
    black_name = str(game.get("black", {}).get("username", "")).lower()
    user_l = username.lower()
    if user_l == white_name:
        return "white"
    if user_l == black_name:
        return "black"
    return None


def detect_opening(game: dict[str, Any]) -> str:
    opening = game.get("opening")
    if isinstance(opening, str) and opening.strip():
        return opening.strip()
    eco_url = game.get("eco")
    if isinstance(eco_url, str) and eco_url.strip():
        slug = eco_url.rstrip("/").split("/")[-1].replace("-", " ").strip()
        if slug:
            return slug.title()
    return "Unknown Opening"


def get_stage_for_ply(ply: int) -> str:
    if ply <= 20:
        return "opening"
    if ply <= 60:
        return "midgame"
    return "endgame"


def evaluate_cp(engine: Any, board: Any, pov_color: Any, depth: int, chess_engine: Any) -> int:
    info = engine.analyse(board, chess_engine.Limit(depth=depth))
    score_obj = info["score"].pov(pov_color)
    return int(score_obj.score(mate_score=100000))


def evaluate_score(engine: Any, board: Any, pov_color: Any, depth: int, chess_engine: Any) -> Any:
    info = engine.analyse(board, chess_engine.Limit(depth=depth))
    return info["score"].pov(pov_color)


def material_points(board: Any, color: Any, chess: Any) -> int:
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    return sum(len(board.pieces(piece_type, color)) * val for piece_type, val in values.items())


def _stage_score(values: list[int]) -> dict[str, Any]:
    raw = (sum(values) / len(values)) if values else 0.0
    score = max(0.0, min(100.0, 60.0 + raw / 10.0))
    grade = "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D" if score >= 50 else "F"
    return {"score": round(score, 1), "grade": grade, "sample_size": len(values)}


def analyze_game_with_engine_pipeline(
    game: dict[str, Any],
    username: str,
    engine_path: str,
    engine_depth: int,
    multipv: int = 2,
) -> GameReview:
    first_pass_depth = max(16, min(18, engine_depth))
    first_pass_multipv = max(4, min(5, multipv if multipv > 1 else 4))
    verify_depth = 26

    player_color = get_player_color(game, username)
    if player_color is None:
        raise RuntimeError("Username not present in game payload")

    chess, chess_pgn, chess_engine = _load_python_chess()
    parsed_game = chess_pgn.read_game(io.StringIO(str(game.get("pgn", ""))))
    if parsed_game is None:
        raise RuntimeError("Could not parse PGN for engine analysis")

    board = parsed_game.board()
    pov_color = chess.WHITE if player_color == "white" else chess.BLACK
    player_rating = int(game.get(player_color, {}).get("rating", 1200) or 1200)

    stage_nets: dict[str, list[int]] = {"opening": [], "midgame": [], "endgame": []}
    eval_deltas: list[int] = []
    reviewed_moves: list[MoveReview] = []
    good_moves: list[dict[str, Any]] = []
    bad_moves: list[dict[str, Any]] = []

    with chess_engine.SimpleEngine.popen_uci(engine_path) as engine:
        analysis_cache: dict[tuple[str, int, int], Any] = {}

        def analyse_cached(board_obj: Any, depth: int, multi: int) -> Any:
            key = (board_obj.fen(), depth, multi)
            if key in analysis_cache:
                return analysis_cache[key]
            info = engine.analyse(board_obj, chess_engine.Limit(depth=depth), multipv=max(1, multi))
            analysis_cache[key] = info
            return info

        engine_name = engine.id.get("name", "unknown")
        node = parsed_game
        ply = 0
        total_nodes = 0
        total_nps = 0
        info_samples = 0
        while node.variations:
            next_node = node.variations[0]
            move = next_node.move
            ply += 1

            if board.turn == pov_color:
                multi = analyse_cached(board, first_pass_depth, first_pass_multipv)
                multi_lines = multi if isinstance(multi, list) else [multi]
                eval_before_score = multi_lines[0]["score"].pov(pov_color)
                eval_before = int(eval_before_score.score(mate_score=100000))
                lines: list[EngineLine] = []
                for idx, info in enumerate(multi_lines, start=1):
                    pv = info.get("pv", [])
                    pv_uci = [m.uci() for m in pv]
                    pv_san: list[str] = []
                    temp = board.copy()
                    for pv_move in pv[:8]:
                        pv_san.append(temp.san(pv_move))
                        temp.push(pv_move)
                    first = pv[0] if pv else move
                    lines.append(
                        EngineLine(
                            multipv=idx,
                            move_uci=first.uci(),
                            move_san=board.san(first),
                            score_cp=int(info["score"].pov(pov_color).score(mate_score=100000)),
                            pv_uci=pv_uci,
                            pv_san=pv_san,
                        )
                    )
                    total_nodes += int(info.get("nodes", 0) or 0)
                    total_nps += int(info.get("nps", 0) or 0)
                    info_samples += 1

                best_line = lines[0]
                best_move = chess.Move.from_uci(best_line.move_uci)
                best_san = best_line.move_san
                san = board.san(move)
                uci = move.uci()
                material_before = material_points(board, pov_color, chess)

                board_after_played = board.copy()
                board_after_played.push(move)
                eval_after_info = analyse_cached(board_after_played, first_pass_depth, 1)
                if isinstance(eval_after_info, list):
                    eval_after_info = eval_after_info[0]
                eval_after_score = eval_after_info["score"].pov(pov_color)
                eval_after = int(eval_after_score.score(mate_score=100000))

                best_board = board.copy()
                best_board.push(best_move)
                best_info = analyse_cached(best_board, first_pass_depth, 1)
                if isinstance(best_info, list):
                    best_info = best_info[0]
                best_score_after = best_info["score"].pov(pov_color)
                best_eval_after = int(best_score_after.score(mate_score=100000))

                material_after = material_points(board_after_played, pov_color, chess)
                delta = eval_after - eval_before
                eval_deltas.append(delta)
                stage_nets[get_stage_for_ply(ply)].append(delta)

                rating_bucket = f"{(player_rating // 200) * 200}-{((player_rating // 200) * 200) + 199}"
                ep_before = score_to_expected_points(eval_before_score, ply=ply, rating_bucket=rating_bucket)
                ep_after = score_to_expected_points(eval_after_score, ply=ply + 1, rating_bucket=rating_bucket)
                ep_best = score_to_expected_points(best_score_after, ply=ply + 1, rating_bucket=rating_bucket)
                ep_loss = expected_points_loss(best_score_after, eval_after_score, ply=ply + 1, rating_bucket=rating_bucket)

                multipv_disagreement = 0
                if len(lines) >= 2:
                    multipv_disagreement = abs(lines[0].score_cp - lines[min(len(lines), 4) - 1].score_cp)

                critical = (
                    abs(delta) >= 180
                    or multipv_disagreement >= 120
                    or abs(eval_before) >= 90000
                    or abs(eval_after) >= 90000
                    or abs(best_eval_after) >= 90000
                )

                verify_used = False
                if critical:
                    verify_used = True
                    deep_after_info = analyse_cached(board_after_played, verify_depth, 1)
                    deep_best_info = analyse_cached(best_board, verify_depth, 1)
                    if isinstance(deep_after_info, list):
                        deep_after_info = deep_after_info[0]
                    if isinstance(deep_best_info, list):
                        deep_best_info = deep_best_info[0]
                    eval_after_score = deep_after_info["score"].pov(pov_color)
                    best_score_after = deep_best_info["score"].pov(pov_color)
                    eval_after = int(eval_after_score.score(mate_score=100000))
                    best_eval_after = int(best_score_after.score(mate_score=100000))
                    ep_after = score_to_expected_points(eval_after_score, ply=ply + 1, rating_bucket=rating_bucket)
                    ep_best = score_to_expected_points(best_score_after, ply=ply + 1, rating_bucket=rating_bucket)
                    ep_loss = expected_points_loss(best_score_after, eval_after_score, ply=ply + 1, rating_bucket=rating_bucket)

                near_best = ep_loss <= 0.02
                is_sacrifice = (material_before - material_after) >= 3 and eval_after >= eval_before - 80
                is_book = ply <= 16 and detect_opening(game) != "Unknown Opening"
                label, label_evidence = assign_move_label(
                    expected_points_loss=ep_loss,
                    is_book=is_book,
                    near_best=near_best,
                    phase=get_stage_for_ply(ply),
                    sound_sacrifice=is_sacrifice,
                    trivially_winning_before=eval_before >= 600,
                    obvious_recapture=("x" in san and "x" in best_san and san == best_san),
                    only_move_save=(eval_before <= -250 and eval_after >= -80 and near_best),
                    only_move_equalize=(eval_before <= -80 and eval_after >= -20 and near_best),
                    punished_opponent_error=(eval_before <= -40 and eval_after >= 80 and near_best),
                    missed_forced_mate=(best_eval_after >= 90000 and eval_after < 90000),
                    missed_large_material_win=(best_eval_after - eval_after >= 300),
                    missed_clear_equalization=(eval_before <= -120 and eval_after <= -120 and best_eval_after >= -20),
                    missed_transition_to_winning=(best_eval_after >= 120 and eval_after < 20),
                )

                played_pv = [san]
                if len(lines) > 1:
                    played_pv = lines[1].pv_san or [san]

                motif_objects = detect_tactical_tags(
                    board_before=board,
                    board_after_played=board_after_played,
                    board_after_best=best_board,
                    played_pv=played_pv,
                    best_pv=best_line.pv_san,
                    move=move,
                    mover_color=pov_color,
                    chess=chess,
                )
                tags = [m["tag"] for m in motif_objects]
                transition = describe_transition(ep_before, ep_after)
                issue_type = classify_issue_type(label, tags, delta, get_stage_for_ply(ply))
                short_expl = build_short_explanation(
                    label,
                    best_san,
                    played_san=san,
                    tags=tags,
                    transition=transition,
                    issue_type=issue_type,
                )
                detailed_expl = build_detailed_explanation(
                    label,
                    best_san,
                    ep_loss,
                    delta,
                    tags,
                    played_san=san,
                    transition=transition,
                    issue_type=issue_type,
                    phase=get_stage_for_ply(ply),
                )

                move_number = (ply + 1) // 2
                move_number_display = f"{move_number}." if ply % 2 == 1 else f"{move_number}..."
                side = "white" if ply % 2 == 1 else "black"

                review = MoveReview(
                    san=san,
                    uci=uci,
                    ply=ply,
                    side=side,
                    label=label,
                    expected_points_before=round(ep_before, 4),
                    expected_points_after_best=round(ep_best, 4),
                    expected_points_after_played=round(ep_after, 4),
                    expected_points_loss=round(ep_loss, 4),
                    best_move_uci=best_line.move_uci,
                    best_move_san=best_san,
                    best_pv=best_line.pv_san,
                    played_pv=played_pv,
                    tactical_tags=tags,
                    short_explanation=short_expl,
                    detailed_explanation=detailed_expl,
                    move_number=move_number,
                    move_number_display=move_number_display,
                    classification_reason=detailed_expl,
                    eval_before_cp=eval_before,
                    eval_after_cp=eval_after,
                    best_eval_after_cp=best_eval_after,
                    label_evidence=label_evidence,
                    engine_metadata={
                        "first_pass_depth": first_pass_depth,
                        "verify_depth": verify_depth if verify_used else None,
                        "verify_used": verify_used,
                        "nodes": int(eval_after_info.get("nodes", 0) or 0),
                        "nps": int(eval_after_info.get("nps", 0) or 0),
                        "multipv": first_pass_multipv,
                        "multipv_disagreement_cp": multipv_disagreement,
                    },
                    fen_before=board.fen(),
                    fen_after=board_after_played.fen(),
                )
                reviewed_moves.append(review)

                if label in {"Best", "Excellent", "Good", "Great", "Brilliant"} or delta >= 80:
                    good_moves.append({"ply": ply, "san": san, "tag": "good", "reason": short_expl, "eval_delta_cp": delta})
                if label in {"Inaccuracy", "Mistake", "Blunder", "Miss"} or delta <= -80:
                    bad_moves.append({"ply": ply, "san": san, "tag": "bad", "reason": short_expl, "eval_delta_cp": delta})

                board.push(move)
            else:
                board.push(move)

            node = next_node

    review = GameReview(
        url=game.get("url"),
        time_class=game.get("time_class"),
        rated=game.get("rated"),
        end_time=game.get("end_time"),
        player_color=player_color,
        player_result=str(game.get(player_color, {}).get("result", "unknown")),
        opening=detect_opening(game),
        stage_performance={
            "opening": _stage_score(stage_nets["opening"]),
            "midgame": _stage_score(stage_nets["midgame"]),
            "endgame": _stage_score(stage_nets["endgame"]),
        },
        engine_version=engine_name,
        engine_warning=None if "Stockfish 18" in str(engine_name) else "Use Stockfish 18+ for latest review quality.",
        engine_depth=engine_depth,
        average_eval_delta_cp=round(sum(eval_deltas) / len(eval_deltas), 1) if eval_deltas else 0.0,
        engine_metadata={
            "first_pass_depth": first_pass_depth,
            "first_pass_multipv": first_pass_multipv,
            "verify_depth": verify_depth,
            "cache_entries": len(analysis_cache),
            "avg_nodes": int(total_nodes / info_samples) if info_samples else 0,
            "avg_nps": int(total_nps / info_samples) if info_samples else 0,
        },
        move_quality_counts={},
        key_moments=[],
        best_missed_opportunities=[],
        tactical_themes={},
        reviewed_moves=reviewed_moves,
        good_moves=good_moves,
        bad_moves=bad_moves,
    )
    # Aggregate summaries for UI/JSON readability.
    counts: dict[str, int] = {}
    themes: dict[str, int] = {}
    for mv in reviewed_moves:
        counts[mv.label] = counts.get(mv.label, 0) + 1
        for t in mv.tactical_tags:
            themes[t] = themes.get(t, 0) + 1

    key_moments = sorted(
        [
            {
                "move_number_display": mv.move_number_display,
                "san": mv.san,
                "label": mv.label,
                "expected_points_loss": mv.expected_points_loss,
                "short_explanation": mv.short_explanation,
            }
            for mv in reviewed_moves
        ],
        key=lambda x: x["expected_points_loss"],
        reverse=True,
    )[:5]

    missed = [
        {
            "move_number_display": mv.move_number_display,
            "san": mv.san,
            "label": mv.label,
            "best_move_san": mv.best_move_san,
            "expected_points_loss": mv.expected_points_loss,
        }
        for mv in reviewed_moves
        if mv.label in {"Miss", "Mistake", "Blunder", "Inaccuracy"}
    ]
    missed.sort(key=lambda x: x["expected_points_loss"], reverse=True)
    review.move_quality_counts = counts
    review.key_moments = key_moments
    review.best_missed_opportunities = missed[:5]
    review.tactical_themes = dict(sorted(themes.items(), key=lambda kv: kv[1], reverse=True))
    return review
