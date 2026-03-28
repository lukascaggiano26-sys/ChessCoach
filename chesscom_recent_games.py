#!/usr/bin/env python3
"""Fetch all Chess.com games for a player from the past two months.

This script uses the public Chess.com API:
- GET /pub/player/{username}/games/archives
- GET monthly archive URLs returned above
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CHESSCOM_BASE = "https://api.chess.com/pub/player"
DEFAULT_TIMEOUT_SECONDS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download every Chess.com game for a user played in the past two months "
            "and write the results to JSON."
        )
    )
    parser.add_argument("username", help="Chess.com username")
    parser.add_argument(
        "--output",
        "-o",
        default="recent_games.json",
        help="Output JSON file path (default: recent_games.json)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=61,
        help=(
            "How many days back to include; defaults to 61 to safely cover two months "
            "regardless of month length"
        ),
    )
    return parser.parse_args()


def month_key_from_archive_url(url: str) -> tuple[int, int]:
    # Archive URLs end in .../YYYY/MM
    year_str, month_str = url.rstrip("/").split("/")[-2:]
    return int(year_str), int(month_str)


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "ChessCoach/1.0 (recent game downloader)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Chess.com API returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Chess.com API for {url}: {exc.reason}") from exc


def get_relevant_archives(username: str, cutoff: datetime) -> list[str]:
    archives_url = f"{CHESSCOM_BASE}/{username}/games/archives"
    payload = fetch_json(archives_url)
    archives = payload.get("archives", [])
    if not isinstance(archives, list):
        raise RuntimeError("Unexpected API response: 'archives' is not a list")

    cutoff_month = (cutoff.year, cutoff.month)
    selected = [
        url
        for url in archives
        if isinstance(url, str) and month_key_from_archive_url(url) >= cutoff_month
    ]
    return selected


def get_games_from_archives(archives: list[str], cutoff_epoch: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for archive_url in archives:
        payload = fetch_json(archive_url)
        monthly_games = payload.get("games", [])
        if not isinstance(monthly_games, list):
            continue

        for game in monthly_games:
            if not isinstance(game, dict):
                continue

            # Chess.com game objects include 'end_time' UNIX timestamp.
            end_time = game.get("end_time")
            if isinstance(end_time, int) and end_time >= cutoff_epoch:
                games.append(game)

    games.sort(key=lambda game: game.get("end_time", 0))
    return games


def main() -> None:
    args = parse_args()
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=args.days)
    cutoff_epoch = int(cutoff.timestamp())

    archives = get_relevant_archives(args.username, cutoff)
    games = get_games_from_archives(archives, cutoff_epoch)

    result = {
        "username": args.username,
        "retrieved_at_utc": now_utc.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "days": args.days,
        "game_count": len(games),
        "games": games,
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Saved {len(games)} games to {output_path}")


if __name__ == "__main__":
    main()
