# ChessCoach

Utility script for pulling all Chess.com game information from the past two months.

## Usage

```bash
python3 chesscom_recent_games.py <chesscom_username> --output recent_games.json
```

### Options

- `--output`, `-o`: output file path (default `recent_games.json`)
- `--days`: lookback window in days (default `61`, which safely covers two months)

## Output

The script saves a JSON document with:

- metadata (`username`, retrieval timestamp, cutoff timestamp)
- `game_count`
- `games`: full game objects as returned by Chess.com's API for games ending on/after the cutoff

## Notes

- Uses Chess.com public archive endpoints.
- Filters games by each game's `end_time` UNIX timestamp.
