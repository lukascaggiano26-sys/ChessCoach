# ChessCoach

A Python tool that downloads a player's recent Chess.com games, runs engine-backed move analysis, and provides quick coaching insights.

## Features

- Pulls games from the last 3 days by default (`--days 3`)
- Detects opening name from Chess.com metadata
- Highlights engine-evaluated "good" and "bad" moves for the selected player
- Adds Chess.com-style move classes in review output (`Best`, `Excellent`, `Good`, `Inaccuracy`, `Mistake`, `Blunder`, plus `Great`/`Brilliant`/`Miss` heuristics)
- Rates performance by game stage:
  - opening
  - midgame
  - endgame
- Includes a simple browser UI for username input and report viewing
- Shows games newest-to-oldest in the UI

## CLI usage

```bash
python3 chesscom_recent_games.py <chesscom_username> --output recent_games_analysis.json
```

### CLI options

- `--output`, `-o`: output file path (default `recent_games_analysis.json`)
- `--days`: lookback window in days (default `3`)
- `--ui`: run a local web UI instead of one-shot CLI output
- `--host`: UI host (default `127.0.0.1`)
- `--port`: UI port (default `8000`)
- `--engine-path`: path to UCI engine binary (default `stockfish`)
- `--engine-depth`: engine depth for per-move analysis (default `12`)

## UI usage

```bash
python3 chesscom_recent_games.py --ui
```

Then open `http://127.0.0.1:8000`, enter a username, and click **Show games**.
From there, click a specific game to run analysis on-demand (engine work starts only for the clicked game).

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

Move quality and stage scoring are produced from a UCI engine (Stockfish-compatible) by measuring evaluation deltas before/after each player move and expected-points loss.

### Requirements for engine analysis

- Install a UCI-compatible engine (**Stockfish 18+ recommended** for best parity with latest review quality).
- Install Python package:

```bash
python3 -m pip install python-chess
```

If `python-chess` is installed for a different interpreter, run:

```bash
$(which python3) -m pip install python-chess
```

When engine dependencies are missing, the app now falls back to heuristic analysis and shows an explicit warning in CLI/UI output instead of crashing.

## Running tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
