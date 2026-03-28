# ChessCoach

A dependency-free Python tool that downloads a player's recent Chess.com games, reviews each game, and provides quick insights.

## Features

- Pulls all games from the last two months by default (`--days 61`)
- Detects opening name from Chess.com metadata
- Highlights heuristic "good" and "bad" moves for the selected player
- Rates performance by game stage:
  - opening
  - midgame
  - endgame
- Includes a simple browser UI for username input and report viewing

## CLI usage

```bash
python3 chesscom_recent_games.py <chesscom_username> --output recent_games_analysis.json
```

### CLI options

- `--output`, `-o`: output file path (default `recent_games_analysis.json`)
- `--days`: lookback window in days (default `61`)
- `--ui`: run a local web UI instead of one-shot CLI output
- `--host`: UI host (default `127.0.0.1`)
- `--port`: UI port (default `8000`)

## UI usage

```bash
python3 chesscom_recent_games.py --ui
```

Then open `http://127.0.0.1:8000`, enter a username, and click **Analyze**.

## Output JSON

The generated JSON includes:

- metadata (`username`, retrieval timestamp, cutoff timestamp)
- `game_count`
- `games` with:
  - opening
  - game URL/result/time class
  - stage performance scores + letter grades
  - lists of flagged good and bad moves

## Important note

Move quality and stage scoring are **heuristics**, not full engine analysis. They are intended as lightweight coaching signals and may miss tactical/contextual nuances.
