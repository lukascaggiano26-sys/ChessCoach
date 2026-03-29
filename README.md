# ChessCoach

A Python tool that downloads a player's recent Chess.com games, runs engine-backed move analysis, and provides quick coaching insights.

## Features

- Pulls games from the last 3 days by default (`--days 3`)
- Detects opening name from Chess.com metadata
- Highlights engine-evaluated "good" and "bad" moves for the selected player
- Adds Chess.com-style move classes in review output (`Best`, `Excellent`, `Good`, `Inaccuracy`, `Mistake`, `Blunder`, plus `Great`/`Brilliant`/`Miss` heuristics)
- Explains why each reviewed move received its label (including the engine’s best move when your move was not best)
- Per-game summary panels: label counts, key moments, best missed opportunities, tactical themes
- Review-table filters by label and motif for casual browsing
- Rates performance by game stage:
  - opening
  - midgame
  - endgame
- Includes a simple browser UI for username input and report viewing
- Shows games newest-to-oldest in the UI

## Modular pipeline layout

- `engine_pipeline.py`: engine orchestration, MultiPV position analysis, game review assembly
- `expected_points.py`: expected-points curve from engine eval
- `classify.py`: move label classification and special-label upgrades
- `motifs.py`: tactical tag extraction
- `explanations.py`: short/detailed label explanations
- `models.py`: dataclasses for `EngineLine`, `PositionAnalysis`, `MoveReview`, `GameReview`

### Expected-points model notes

- Faithful to public Chess.com description: move quality is based on expected points from engine evaluation.
- Implementation inference: expectation is computed via python-chess score semantics (`score.wdl`) with mate-aware ordering.
- `rating_bucket` is included as a forward-compatible calibration hook and is currently not yet applied to expectation math.

### Review strength configuration

- First pass: depth 16-18 with MultiPV 4-5 across moves.
- Deep verification pass: depth 24-30 for critical moves (mate scores, large eval swings, high MultiPV disagreement).
- Engine results are cached by `FEN + depth + multipv`.
- JSON/UI surfaces engine metadata including depth, nodes, nps, and multipv counts.

### Explanation system

- `explanations.py` uses deterministic templates (no LLM calls).
- Every reviewed move receives:
  - one-sentence `short_explanation`
  - 2-5 sentence `detailed_explanation`
- Explanations contrast played vs best move, mention motif/issue type when detectable, and include game-state transitions when relevant.

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
