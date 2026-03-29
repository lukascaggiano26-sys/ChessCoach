#!/usr/bin/env python3
"""Fetch and review recent Chess.com games.

Features:
- Download games for a user from the last N days (default 61 ~ two months)
- Identify likely opening from Chess.com metadata
- Heuristically tag good/bad moves for the player
- Score player performance by stage: opening, middlegame, endgame
- Optional built-in local web UI (--ui)
"""

from __future__ import annotations

import argparse
import html
import importlib
import importlib.util
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen

from engine_pipeline import analyze_game_with_engine_pipeline

CHESSCOM_BASE = "https://api.chess.com/pub/player"
DEFAULT_TIMEOUT_SECONDS = 30

MOVE_NUMBER_TOKEN = re.compile(r"^\d+\.(\.\.)?$")
HEADER_LINE = re.compile(r"^\[.*\]$")
COMMENT_BLOCK = re.compile(r"\{[^}]*\}")
NAG_TOKEN = re.compile(r"\$\d+")
RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}


@dataclass
class MoveReview:
    ply: int
    san: str
    tag: str
    reason: str
    eval_delta_cp: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download and review every Chess.com game for a user played in the past "
            "two months."
        )
    )
    parser.add_argument("username", nargs="?", help="Chess.com username")
    parser.add_argument(
        "--output",
        "-o",
        default="recent_games_analysis.json",
        help="Output JSON file path (default: recent_games_analysis.json)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="How many days back to include (default: 3)",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch a simple local web UI instead of writing one-shot output",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for UI server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for UI server (default: 8000)",
    )
    parser.add_argument(
        "--engine-path",
        default="stockfish",
        help="Path to UCI engine binary (default: stockfish)",
    )
    parser.add_argument(
        "--engine-depth",
        type=int,
        default=12,
        help="Engine search depth for per-move analysis (default: 12)",
    )
    return parser.parse_args()


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "ChessCoach/1.0 (review tool)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Chess.com API returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Chess.com API for {url}: {exc.reason}") from exc


def month_key_from_archive_url(url: str) -> tuple[int, int]:
    year_str, month_str = url.rstrip("/").split("/")[-2:]
    return int(year_str), int(month_str)


def get_relevant_archives(username: str, cutoff: datetime) -> list[str]:
    archives_url = f"{CHESSCOM_BASE}/{username}/games/archives"
    payload = fetch_json(archives_url)
    archives = payload.get("archives", [])
    if not isinstance(archives, list):
        raise RuntimeError("Unexpected API response: 'archives' is not a list")

    cutoff_month = (cutoff.year, cutoff.month)
    return [
        url
        for url in archives
        if isinstance(url, str) and month_key_from_archive_url(url) >= cutoff_month
    ]


def get_games_from_archives(archives: list[str], cutoff_epoch: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for archive_url in archives:
        payload = fetch_json(archive_url)
        monthly_games = payload.get("games", [])
        if not isinstance(monthly_games, list):
            continue

        for game in monthly_games:
            end_time = game.get("end_time")
            if isinstance(game, dict) and isinstance(end_time, int) and end_time >= cutoff_epoch:
                games.append(game)

    games.sort(key=lambda game: game.get("end_time", 0), reverse=True)
    return games


def extract_san_tokens(pgn: str) -> list[str]:
    body = []
    for line in pgn.splitlines():
        if not HEADER_LINE.match(line.strip()):
            body.append(line)

    text = " ".join(body)
    text = COMMENT_BLOCK.sub(" ", text)
    text = NAG_TOKEN.sub(" ", text)
    text = text.replace("\n", " ")
    tokens = [token.strip() for token in text.split() if token.strip()]

    clean: list[str] = []
    for token in tokens:
        if token in RESULT_TOKENS:
            continue
        if MOVE_NUMBER_TOKEN.match(token):
            continue
        if token.endswith(".") and token[:-1].isdigit():
            continue
        clean.append(token)
    return clean


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

    pgn = str(game.get("pgn", ""))
    for line in pgn.splitlines():
        if line.startswith("[Opening "):
            parts = line.split('"')
            if len(parts) >= 2 and parts[1].strip():
                return parts[1].strip()
    return "Unknown Opening"


def get_stage_for_ply(ply: int) -> str:
    if ply <= 20:
        return "opening"
    if ply <= 60:
        return "midgame"
    return "endgame"


def review_move(san: str, ply: int) -> tuple[str | None, str, int]:
    good_score = 0
    bad_score = 0
    reasons: list[str] = []

    if "#" in san:
        good_score += 4
        reasons.append("delivers checkmate")
    if "+" in san:
        good_score += 1
        reasons.append("applies check")
    if "x" in san:
        good_score += 1
        reasons.append("captures material")
    if "=" in san:
        good_score += 3
        reasons.append("promotes pawn")
    if san.startswith("O-O"):
        good_score += 1
        reasons.append("castles for king safety")
    if "!" in san:
        good_score += 2
        reasons.append("annotated as strong")

    if "?" in san:
        bad_score += 3
        reasons.append("annotated as mistake/blunder")
    if ply <= 16 and san.startswith("Q") and "x" not in san:
        bad_score += 1
        reasons.append("early queen move without capture")
    if ply <= 20 and san.startswith("K"):
        bad_score += 2
        reasons.append("early king move")

    net = good_score - bad_score
    if net >= 2:
        return "good", ", ".join(reasons) or "positive move pattern", net
    if net <= -2:
        return "bad", ", ".join(reasons) or "negative move pattern", net
    return None, ", ".join(reasons), net


def stage_grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "F"


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


def evaluate_cp(engine: Any, board: Any, pov_color: Any, depth: int, chess_engine: Any) -> int:
    info = engine.analyse(board, chess_engine.Limit(depth=depth))
    score_obj = info["score"].pov(pov_color)
    return int(score_obj.score(mate_score=100000))


def expected_points_from_cp(eval_cp: int, rating: int) -> float:
    """Approximate expected points from centipawn eval and player rating."""
    scale = max(220.0, 420.0 - (rating / 6.0))
    return 1.0 / (1.0 + 10 ** (-eval_cp / scale))


def material_points(board: Any, color: Any, chess: Any) -> int:
    values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    total = 0
    for piece_type, val in values.items():
        total += len(board.pieces(piece_type, color)) * val
    return total


def classify_expected_points_loss(loss: float) -> str:
    if loss <= 0.0:
        return "Best"
    if loss < 0.02:
        return "Excellent"
    if loss < 0.05:
        return "Good"
    if loss < 0.10:
        return "Inaccuracy"
    if loss < 0.20:
        return "Mistake"
    return "Blunder"


def explain_classification(
    classification: str,
    san: str,
    best_san: str,
    ep_loss: float,
    delta_cp: int,
) -> str:
    if classification == "Brilliant":
        return "Brilliant move: strong engine approval plus a practical sacrifice that keeps your position stable."
    if classification == "Great":
        return "Great move: significantly improved your evaluation in a critical moment."
    if classification == "Best":
        return "Best move: matches the top engine continuation."
    if classification == "Excellent":
        return f"Excellent move: close to best. Engine's top move was {best_san}."
    if classification == "Good":
        return f"Good move: solid practical choice. Best move was {best_san}."
    if classification == "Inaccuracy":
        return f"Inaccuracy: playable, but not optimal. Best move was {best_san}."
    if classification == "Mistake":
        return f"Mistake: this gave away too much value. Best move was {best_san}."
    if classification == "Blunder":
        return f"Blunder: major evaluation swing ({delta_cp:+} cp). Best move was {best_san}."
    if classification == "Miss":
        return f"Miss: there was a stronger continuation to convert your advantage. Best move was {best_san}."
    return f"{classification}: engine-based classification for move {san}."


def analyze_game_with_engine(
    game: dict[str, Any],
    username: str,
    engine_path: str,
    engine_depth: int,
) -> dict[str, Any]:
    try:
        review = analyze_game_with_engine_pipeline(
            game=game,
            username=username,
            engine_path=engine_path,
            engine_depth=engine_depth,
            multipv=2,
        )
        payload = review.to_dict()
        for move in payload.get("reviewed_moves", []):
            # Backward compatibility with earlier key name
            move["classification"] = move.get("label")
        return payload
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Engine binary not found at '{engine_path}'. Install Stockfish or pass --engine-path."
        ) from exc


def analyze_game_heuristic(game: dict[str, Any], username: str) -> dict[str, Any]:
    """Fallback analysis path used when engine dependencies are unavailable."""
    player_color = get_player_color(game, username)
    if player_color is None:
        raise RuntimeError("Username not present in game payload")

    tokens = extract_san_tokens(str(game.get("pgn", "")))
    player_is_white = player_color == "white"

    highlights: list[MoveReview] = []
    stage_nets: dict[str, list[int]] = {"opening": [], "midgame": [], "endgame": []}

    for idx, san in enumerate(tokens):
        ply = idx + 1
        is_white_move = idx % 2 == 0
        if is_white_move != player_is_white:
            continue

        tag, reason, net = review_move(san, ply)
        stage_nets[get_stage_for_ply(ply)].append(net)
        if tag is not None:
            highlights.append(MoveReview(ply=ply, san=san, tag=tag, reason=reason, eval_delta_cp=None))

    def stage_score(values: list[int]) -> dict[str, Any]:
        raw = (sum(values) / len(values)) if values else 0.0
        score = max(0.0, min(100.0, 60.0 + raw * 12.0))
        return {"score": round(score, 1), "grade": stage_grade(score), "sample_size": len(values)}

    opening_name = detect_opening(game)
    player_result = str(game.get(player_color, {}).get("result", "unknown"))
    return {
        "url": game.get("url"),
        "time_class": game.get("time_class"),
        "rated": game.get("rated"),
        "end_time": game.get("end_time"),
        "player_color": player_color,
        "player_result": player_result,
        "opening": opening_name,
        "stage_performance": {
            "opening": stage_score(stage_nets["opening"]),
            "midgame": stage_score(stage_nets["midgame"]),
            "endgame": stage_score(stage_nets["endgame"]),
        },
        "engine_version": None,
        "engine_warning": "Engine unavailable. Install python-chess and Stockfish 18+.",
        "engine_depth": None,
        "average_eval_delta_cp": None,
        "reviewed_moves": [],
        "good_moves": [h.__dict__ for h in highlights if h.tag == "good"],
        "bad_moves": [h.__dict__ for h in highlights if h.tag == "bad"],
    }


def analyze_recent_games(
    username: str,
    days: int,
    engine_path: str,
    engine_depth: int,
) -> dict[str, Any]:
    recent = fetch_recent_games(username, days)
    games = recent["games"]
    now_utc = recent["retrieved_at_utc"]
    cutoff = recent["cutoff_utc"]

    engine_error: str | None = None
    analyzed_games: list[dict[str, Any]]
    try:
        analyzed_games = [
            analyze_game_with_engine(game, username, engine_path=engine_path, engine_depth=engine_depth)
            for game in games
        ]
        analysis_mode = "engine"
    except RuntimeError as exc:
        engine_error = str(exc)
        analyzed_games = [analyze_game_heuristic(game, username) for game in games]
        analysis_mode = "heuristic_fallback"

    return {
        "username": username,
        "retrieved_at_utc": now_utc,
        "cutoff_utc": cutoff,
        "days": days,
        "engine_path": engine_path,
        "engine_depth": engine_depth,
        "analysis_mode": analysis_mode,
        "engine_error": engine_error,
        "game_count": len(analyzed_games),
        "games": analyzed_games,
    }


def fetch_recent_games(username: str, days: int) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)
    cutoff_epoch = int(cutoff.timestamp())

    archives = get_relevant_archives(username, cutoff)
    games = get_games_from_archives(archives, cutoff_epoch)

    return {
        "username": username,
        "retrieved_at_utc": now_utc.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "days": days,
        "game_count": len(games),
        "games": games,
    }


def _shell_layout(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        "body{font-family:Inter,Arial,sans-serif;background:#262421;color:#f5f5f5;margin:0;line-height:1.45;}"
        ".top{background:#312e2b;padding:12px 18px;font-weight:700;border-bottom:1px solid #3b3936;position:sticky;top:0;z-index:9;}"
        ".wrap{max-width:1180px;margin:0 auto;padding:20px;}"
        ".panel{background:#312e2b;border:1px solid #3b3936;border-radius:10px;padding:18px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,.2);}"
        "a{color:#81b64c;text-decoration:none;} a:hover{text-decoration:underline;}"
        "input,select,button{padding:.58rem .62rem;border-radius:7px;border:1px solid #555;background:#1f1f1f;color:#fff;}"
        "button{background:#81b64c;color:#111;font-weight:700;border:none;cursor:pointer;}"
        "table{width:100%;border-collapse:collapse;font-size:.95rem;}"
        "th,td{padding:8px 10px;border-bottom:1px solid #3b3936;vertical-align:top;}"
        "tr:hover td{background:#2b2926;}"
        ".game{display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #3b3936;gap:12px;}"
        ".muted{color:#b7b7b7;font-size:.92rem;}"
        ".chip{background:#3b3936;color:#ddd;padding:3px 8px;border-radius:12px;font-size:.8rem;display:inline-block;margin-right:6px;}"
        ".grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;}"
        ".statlist{margin:0;padding-left:18px;}"
        ".helper{font-size:.88rem;color:#cfcfcf;}"
        "</style></head><body><div class='top'>ChessCoach • Rapid Review</div><div class='wrap'>"
        f"{body}</div></body></html>"
    )


def render_home(error: str | None = None) -> str:
    err = f"<p style='color:#ff8f8f'>{html.escape(error)}</p>" if error else ""
    body = (
        "<div class='panel'><h2>Load your recent games</h2>"
        "<form method='get' action='/games'>"
        "<label>Username</label><br><input name='username' required><br><br>"
        "<label>Days</label><br><input name='days' type='number' value='3' min='1' max='365'><br><br>"
        "<button type='submit'>Show games</button></form>"
        "<p class='muted'>Tip: analysis runs only when you open a specific game, so loading is fast.</p>"
        f"{err}</div>"
    )
    return _shell_layout("ChessCoach", body)


def render_games_list(username: str, days: int, recent: dict[str, Any], error: str | None = None) -> str:
    if error:
        return render_home(error)
    rows = []
    for game in recent.get("games", []):
        white = str(game.get("white", {}).get("username", "White"))
        black = str(game.get("black", {}).get("username", "Black"))
        tclass = str(game.get("time_class", "n/a"))
        end_time = int(game.get("end_time", 0) or 0)
        dt = datetime.fromtimestamp(end_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if end_time else "unknown"
        url = str(game.get("url", ""))
        review_href = f"/review?username={quote_plus(username)}&days={days}&game_url={quote_plus(url)}"
        rows.append(
            "<div class='game'>"
            f"<div><strong>{html.escape(white)} vs {html.escape(black)}</strong> "
            f"<span class='chip'>{html.escape(tclass)}</span><div class='muted'>{dt}</div></div>"
            f"<a href='{review_href}'>Analyze</a>"
            "</div>"
        )
    content = "".join(rows) or "<p>No games found for that range.</p>"
    body = (
        f"<div class='panel'><h2>{html.escape(username)} • Last {days} day(s)</h2>"
        "<p class='muted'>Select any game below to run review analysis.</p>"
        f"{content}</div>"
        "<div><a href='/'>← Back</a></div>"
    )
    return _shell_layout("Game List", body)


def render_review(
    username: str,
    days: int,
    analysis: dict[str, Any],
    mode_note: str | None = None,
    selected_label: str = "",
    selected_motif: str = "",
) -> str:
    stage = analysis.get("stage_performance", {})
    opening_stage = stage.get("opening", {"score": "n/a", "grade": "n/a"})
    midgame_stage = stage.get("midgame", {"score": "n/a", "grade": "n/a"})
    endgame_stage = stage.get("endgame", {"score": "n/a", "grade": "n/a"})
    good_items = "".join(
        f"<li>Ply {m['ply']}: {html.escape(m['san'])} ({html.escape(m['reason'])})</li>"
        for m in analysis.get("good_moves", [])[:10]
    ) or "<li>No strong positive swings flagged.</li>"
    bad_items = "".join(
        f"<li>Ply {m['ply']}: {html.escape(m['san'])} ({html.escape(m['reason'])})</li>"
        for m in analysis.get("bad_moves", [])[:10]
    ) or "<li>No major drops flagged.</li>"
    warning = f"<p style='color:#ffcd73'>{html.escape(mode_note)}</p>" if mode_note else ""
    engine_warning = analysis.get("engine_warning")
    engine_meta = (
        f"<p class='muted'>Engine: {html.escape(str(analysis.get('engine_version', 'n/a')))} "
        f"(depth {html.escape(str(analysis.get('engine_depth', 'n/a')))}).</p>"
    )
    meta = analysis.get("engine_metadata", {})
    if isinstance(meta, dict):
        engine_meta += (
            f"<p class='muted'>MultiPV: {html.escape(str(meta.get('first_pass_multipv', 'n/a')))} | "
            f"Avg nodes: {html.escape(str(meta.get('avg_nodes', 'n/a')))} | "
            f"Avg nps: {html.escape(str(meta.get('avg_nps', 'n/a')))}</p>"
        )
    if engine_warning:
        engine_meta += f"<p style='color:#ffcd73'>{html.escape(str(engine_warning))}</p>"
    reviewed_moves = analysis.get("reviewed_moves", [])
    if selected_label:
        reviewed_moves = [m for m in reviewed_moves if str(m.get("classification", m.get("label", ""))) == selected_label]
    if selected_motif:
        reviewed_moves = [
            m
            for m in reviewed_moves
            if selected_motif in list(m.get("tactical_tags", []))
        ]

    labels = sorted({str(m.get("classification", m.get("label", ""))) for m in analysis.get("reviewed_moves", []) if m})
    motifs = sorted({t for m in analysis.get("reviewed_moves", []) for t in m.get("tactical_tags", [])})

    reviewed_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(m.get('move_number_display', m.get('ply'))))}</td><td>{html.escape(str(m.get('san')))}</td>"
        f"<td>{html.escape(str(m.get('classification')))}</td>"
        f"<td>{html.escape(str(m.get('best_move_san', '')))}</td>"
        f"<td>{html.escape(str(m.get('expected_points_loss', '')))}</td>"
        f"<td>{html.escape(', '.join(m.get('tactical_tags', [])))}</td>"
        "<td>"
        f"{html.escape(str(m.get('short_explanation', m.get('classification_reason', ''))))}"
        f"<details><summary>Details</summary>{html.escape(str(m.get('detailed_explanation', m.get('classification_reason', ''))))}</details>"
        "</td>"
        "</tr>"
        for m in reviewed_moves[:50]
    ) or "<tr><td colspan='7'>No moves match current filters.</td></tr>"

    quality_counts = analysis.get("move_quality_counts", {})
    counts_html = "".join(f"<li>{html.escape(k)}: {v}</li>" for k, v in quality_counts.items()) or "<li>n/a</li>"
    key_moments = analysis.get("key_moments", [])
    key_html = "".join(
        f"<li>{km.get('move_number_display')} {html.escape(str(km.get('san')))} — {html.escape(str(km.get('label')))} (EP loss {km.get('expected_points_loss')})</li>"
        for km in key_moments
    ) or "<li>n/a</li>"
    missed = analysis.get("best_missed_opportunities", [])
    missed_html = "".join(
        f"<li>{m.get('move_number_display')} {html.escape(str(m.get('san')))} | best was {html.escape(str(m.get('best_move_san')))}</li>"
        for m in missed
    ) or "<li>n/a</li>"
    themes = analysis.get("tactical_themes", {})
    themes_html = "".join(f"<li>{html.escape(t)}: {c}</li>" for t, c in themes.items()) or "<li>n/a</li>"

    label_opts = "".join(
        f"<option value='{html.escape(lbl)}' {'selected' if lbl == selected_label else ''}>{html.escape(lbl)}</option>"
        for lbl in labels
    )
    motif_opts = "".join(
        f"<option value='{html.escape(mt)}' {'selected' if mt == selected_motif else ''}>{html.escape(mt)}</option>"
        for mt in motifs
    )
    filter_form = (
        f"<form method='get' action='/review'>"
        f"<input type='hidden' name='username' value='{html.escape(username)}'>"
        f"<input type='hidden' name='days' value='{days}'>"
        f"<input type='hidden' name='game_url' value='{html.escape(str(analysis.get('url', '')))}'>"
        "<label>Filter label</label><br><select name='label'><option value=''>All</option>"
        f"{label_opts}"
        "</select><br><label>Filter motif</label><br><select name='motif'><option value=''>All</option>"
        f"{motif_opts}"
        "</select><br><br><button type='submit'>Apply filters</button></form>"
    )
    body = (
        "<div class='panel'>"
        f"<h2>{html.escape(str(analysis.get('opening', 'Unknown Opening')))}</h2>"
        f"<p><span class='chip'>{html.escape(str(analysis.get('time_class', 'n/a')))}</span> "
        f"Result: <strong>{html.escape(str(analysis.get('player_result', 'unknown')))}</strong></p>"
        f"{warning}"
        f"{engine_meta}"
        f"{filter_form}"
        "<p class='helper'>Use filters to focus on one label or tactical motif.</p>"
        "<ul class='statlist'>"
        f"<li>Opening score: {opening_stage['score']} ({opening_stage['grade']})</li>"
        f"<li>Midgame score: {midgame_stage['score']} ({midgame_stage['grade']})</li>"
        f"<li>Endgame score: {endgame_stage['score']} ({endgame_stage['grade']})</li>"
        "</ul>"
        "<p><strong>Good moves</strong></p><ul>" + good_items + "</ul>"
        "<p><strong>Bad moves</strong></p><ul>" + bad_items + "</ul>"
        "<p><strong>Move classifications (Chess.com-style)</strong></p>"
        "<table>"
        "<tr><th align='left'>Move #</th><th align='left'>Move</th><th align='left'>Class</th><th align='left'>Best</th><th align='left'>EP Loss</th><th align='left'>Motifs</th><th align='left'>Why</th></tr>"
        + reviewed_rows
        + "</table>"
        "<div class='grid'>"
        "<div><p><strong>Move-quality counts by label</strong></p><ul class='statlist'>" + counts_html + "</ul></div>"
        "<div><p><strong>Tactical themes detected</strong></p><ul class='statlist'>" + themes_html + "</ul></div>"
        "<div><p><strong>Key moments</strong></p><ul class='statlist'>" + key_html + "</ul></div>"
        "<div><p><strong>Best missed opportunities</strong></p><ul class='statlist'>" + missed_html + "</ul></div>"
        "</div>"
        f"<p><a target='_blank' href='{html.escape(str(analysis.get('url', '#')))}'>Open full game on Chess.com</a></p>"
        "</div>"
        f"<div><a href='/games?username={html.escape(username)}&days={days}'>← Back to game list</a></div>"
    )
    return _shell_layout("Game Review", body)


def run_ui(host: str, port: int, engine_path: str, engine_depth: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                payload = Path("ui/index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path.startswith("/ui/"):
                rel = parsed.path[len("/ui/") :]
                f = Path("ui") / rel
                if not f.exists():
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not Found")
                    return
                payload = f.read_bytes()
                ctype = "text/plain; charset=utf-8"
                if f.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                if f.suffix == ".js":
                    ctype = "application/javascript; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/games":
                params = parse_qs(parsed.query)
                username = params.get("username", [""])[0].strip()
                days_raw = params.get("days", ["3"])[0]
                try:
                    days = int(days_raw)
                    if days < 1:
                        raise ValueError("days must be >= 1")
                except ValueError:
                    days = 3

                data: dict[str, Any]
                if not username:
                    data = {"error": "username required", "games": []}
                else:
                    try:
                        recent = fetch_recent_games(username, days)
                        games = []
                        for g in recent.get("games", []):
                            games.append(
                                {
                                    "url": g.get("url"),
                                    "white": g.get("white", {}).get("username", "White"),
                                    "black": g.get("black", {}).get("username", "Black"),
                                    "time_class": g.get("time_class"),
                                    "end": datetime.fromtimestamp(int(g.get("end_time", 0) or 0), tz=timezone.utc).isoformat(),
                                }
                            )
                        data = {"username": username, "days": days, "games": games}
                    except RuntimeError as exc:
                        data = {"error": str(exc), "games": []}
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/review":
                params = parse_qs(parsed.query)
                username = params.get("username", [""])[0].strip()
                game_url = params.get("game_url", [""])[0].strip()
                days_raw = params.get("days", ["3"])[0]
                try:
                    days = int(days_raw)
                except ValueError:
                    days = 3
                if not username or not game_url:
                    data = {"error": "Missing username or game URL."}
                else:
                    try:
                        recent = fetch_recent_games(username, days)
                        target = next((g for g in recent["games"] if str(g.get("url", "")) == game_url), None)
                        if target is None:
                            raise RuntimeError("Game not found in current date window.")
                        try:
                            analysis = analyze_game_with_engine(target, username, engine_path, engine_depth)
                        except RuntimeError as exc:
                            analysis = analyze_game_heuristic(target, username)
                            analysis["mode_note"] = f"{exc} | Using heuristic fallback."
                        data = analysis
                    except RuntimeError as exc:
                        data = {"error": str(exc)}
                payload = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            not_found = b"Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(not_found)))
            self.end_headers()
            self.wfile.write(not_found)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = HTTPServer((host, port), Handler)
    print(f"UI running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    args = parse_args()
    if args.ui:
        run_ui(args.host, args.port, args.engine_path, args.engine_depth)
        return

    if not args.username:
        raise SystemExit("username is required unless --ui is used")

    result = analyze_recent_games(
        args.username,
        args.days,
        engine_path=args.engine_path,
        engine_depth=args.engine_depth,
    )
    output_path = Path(args.output)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved analysis for {result['game_count']} games to {output_path}")


if __name__ == "__main__":
    main()
