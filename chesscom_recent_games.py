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


def analyze_game_with_engine(
    game: dict[str, Any],
    username: str,
    engine_path: str,
    engine_depth: int,
) -> dict[str, Any]:
    player_color = get_player_color(game, username)
    if player_color is None:
        raise RuntimeError("Username not present in game payload")

    chess, chess_pgn, chess_engine = _load_python_chess()
    pgn_text = str(game.get("pgn", ""))
    parsed_game = chess_pgn.read_game(io.StringIO(pgn_text))
    if parsed_game is None:
        raise RuntimeError("Could not parse PGN for engine analysis")

    board = parsed_game.board()
    player_is_white = player_color == "white"
    pov_color = chess.WHITE if player_is_white else chess.BLACK
    highlights: list[MoveReview] = []
    stage_nets: dict[str, list[int]] = {"opening": [], "midgame": [], "endgame": []}
    eval_deltas: list[int] = []

    try:
        with chess_engine.SimpleEngine.popen_uci(engine_path) as engine:
            node = parsed_game
            ply = 0
            while node.variations:
                next_node = node.variations[0]
                move = next_node.move
                ply += 1

                if board.turn == pov_color:
                    eval_before = evaluate_cp(engine, board, pov_color, engine_depth, chess_engine)
                    san = board.san(move)
                    board.push(move)
                    eval_after = evaluate_cp(engine, board, pov_color, engine_depth, chess_engine)
                    delta = eval_after - eval_before
                    eval_deltas.append(delta)

                    stage_nets[get_stage_for_ply(ply)].append(delta)

                    if delta >= 80:
                        highlights.append(
                            MoveReview(
                                ply=ply,
                                san=san,
                                tag="good",
                                reason="engine evaluation improved significantly",
                                eval_delta_cp=delta,
                            )
                        )
                    elif delta <= -80:
                        highlights.append(
                            MoveReview(
                                ply=ply,
                                san=san,
                                tag="bad",
                                reason="engine evaluation dropped significantly",
                                eval_delta_cp=delta,
                            )
                        )
                else:
                    board.push(move)

                node = next_node
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Engine binary not found at '{engine_path}'. Install Stockfish or pass --engine-path."
        ) from exc

    def stage_score(values: list[int]) -> dict[str, Any]:
        if not values:
            raw = 0.0
        else:
            raw = sum(values) / len(values)
        score = max(0.0, min(100.0, 60.0 + raw / 10.0))
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
        "engine_depth": engine_depth,
        "average_eval_delta_cp": round(sum(eval_deltas) / len(eval_deltas), 1) if eval_deltas else 0.0,
        "good_moves": [h.__dict__ for h in highlights if h.tag == "good"],
        "bad_moves": [h.__dict__ for h in highlights if h.tag == "bad"],
    }


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
        "engine_depth": None,
        "average_eval_delta_cp": None,
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
        "body{font-family:Inter,Arial,sans-serif;background:#262421;color:#f5f5f5;margin:0;}"
        ".top{background:#312e2b;padding:12px 18px;font-weight:700;border-bottom:1px solid #3b3936;}"
        ".wrap{max-width:1100px;margin:0 auto;padding:18px;}"
        ".panel{background:#312e2b;border:1px solid #3b3936;border-radius:8px;padding:16px;margin-bottom:14px;}"
        "a{color:#81b64c;text-decoration:none;} a:hover{text-decoration:underline;}"
        "input,button{padding:.6rem;border-radius:6px;border:1px solid #555;background:#1f1f1f;color:#fff;}"
        "button{background:#81b64c;color:#111;font-weight:700;border:none;cursor:pointer;}"
        ".game{display:flex;justify-content:space-between;align-items:center;padding:10px;border-bottom:1px solid #3b3936;}"
        ".muted{color:#b7b7b7;font-size:.92rem;}"
        ".chip{background:#3b3936;color:#ddd;padding:3px 8px;border-radius:12px;font-size:.8rem;}"
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
        "<p class='muted'>Engine analysis runs only when you open a specific game to save compute.</p>"
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
        "<p class='muted'>Select a game to start engine+coach analysis.</p>"
        f"{content}</div>"
        "<div><a href='/'>← Back</a></div>"
    )
    return _shell_layout("Game List", body)


def coach_advice(analysis: dict[str, Any]) -> list[str]:
    """Energetic, practical coaching voice inspired by creator-style breakdowns."""
    tips: list[str] = []
    stage = analysis.get("stage_performance", {})
    op = stage.get("opening", {}).get("score", 0)
    mg = stage.get("midgame", {}).get("score", 0)
    eg = stage.get("endgame", {}).get("score", 0)
    bad = analysis.get("bad_moves", [])
    good = analysis.get("good_moves", [])

    tips.append("Love the ambition—now let’s turn this into clean, repeatable chess.")
    if op < 55:
        tips.append("Opening needs structure: prioritize development + king safety before side adventures.")
    if mg < 55:
        tips.append("Midgame focus: pause and ask, 'What changed after my opponent’s move?'")
    if eg < 55:
        tips.append("Endgame discipline: activate king early and convert with simple plans, not flashy moves.")
    if bad:
        first_bad = bad[0]
        tips.append(
            f"Critical moment: ply {first_bad.get('ply')} ({first_bad.get('san')}) dropped your eval—slow down there."
        )
    if good:
        first_good = good[0]
        tips.append(
            f"Keep this energy: ply {first_good.get('ply')} ({first_good.get('san')}) was a strong practical decision."
        )
    tips.append("Training task: review this game once without engine, then once with engine and compare your candidate moves.")
    return tips


def render_review(username: str, days: int, analysis: dict[str, Any], mode_note: str | None = None) -> str:
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
    tips = "".join(f"<li>{html.escape(t)}</li>" for t in coach_advice(analysis))
    warning = f"<p style='color:#ffcd73'>{html.escape(mode_note)}</p>" if mode_note else ""
    body = (
        "<div class='panel'>"
        f"<h2>{html.escape(str(analysis.get('opening', 'Unknown Opening')))}</h2>"
        f"<p><span class='chip'>{html.escape(str(analysis.get('time_class', 'n/a')))}</span> "
        f"Result: <strong>{html.escape(str(analysis.get('player_result', 'unknown')))}</strong></p>"
        f"{warning}"
        "<ul>"
        f"<li>Opening score: {opening_stage['score']} ({opening_stage['grade']})</li>"
        f"<li>Midgame score: {midgame_stage['score']} ({midgame_stage['grade']})</li>"
        f"<li>Endgame score: {endgame_stage['score']} ({endgame_stage['grade']})</li>"
        "</ul>"
        "<p><strong>Good moves</strong></p><ul>" + good_items + "</ul>"
        "<p><strong>Bad moves</strong></p><ul>" + bad_items + "</ul>"
        "<p><strong>Coach notes (Akeem-style energy)</strong></p><ul>" + tips + "</ul>"
        f"<p><a target='_blank' href='{html.escape(str(analysis.get('url', '#')))}'>Open full game on Chess.com</a></p>"
        "</div>"
        f"<div><a href='/games?username={html.escape(username)}&days={days}'>← Back to game list</a></div>"
    )
    return _shell_layout("Game Review", body)


def run_ui(host: str, port: int, engine_path: str, engine_depth: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/games", "/review"}:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

            if parsed.path == "/":
                payload = render_home().encode("utf-8")
            elif parsed.path == "/games":
                params = parse_qs(parsed.query)
                username = params.get("username", [""])[0].strip()
                days_raw = params.get("days", ["3"])[0]
                try:
                    days = int(days_raw)
                    if days < 1:
                        raise ValueError("days must be >= 1")
                except ValueError:
                    days = 3

                if username:
                    try:
                        recent = fetch_recent_games(username, days)
                        payload = render_games_list(username, days, recent).encode("utf-8")
                    except RuntimeError as exc:
                        payload = render_games_list(username, days, {}, error=str(exc)).encode("utf-8")
                else:
                    payload = render_home("Please provide a username.").encode("utf-8")
            else:  # /review
                params = parse_qs(parsed.query)
                username = params.get("username", [""])[0].strip()
                game_url = params.get("game_url", [""])[0].strip()
                days_raw = params.get("days", ["3"])[0]
                try:
                    days = int(days_raw)
                except ValueError:
                    days = 3
                if not username or not game_url:
                    payload = render_home("Missing username or game URL.").encode("utf-8")
                else:
                    try:
                        recent = fetch_recent_games(username, days)
                        target = next((g for g in recent["games"] if str(g.get("url", "")) == game_url), None)
                        if target is None:
                            raise RuntimeError("Game not found in current date window.")
                        mode_note = None
                        try:
                            analysis = analyze_game_with_engine(target, username, engine_path, engine_depth)
                        except RuntimeError as exc:
                            analysis = analyze_game_heuristic(target, username)
                            mode_note = f"{exc} | Using heuristic fallback."
                        payload = render_review(username, days, analysis, mode_note=mode_note).encode("utf-8")
                    except RuntimeError as exc:
                        payload = render_home(str(exc)).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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
