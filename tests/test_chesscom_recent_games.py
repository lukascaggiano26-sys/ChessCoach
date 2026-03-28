import unittest

import chesscom_recent_games as cc


class ChessCoachAnalysisTests(unittest.TestCase):
    def test_extract_san_tokens_removes_headers_and_results(self):
        pgn = """[Event \"Live Chess\"]
[Opening \"Italian Game\"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0
"""
        self.assertEqual(
            cc.extract_san_tokens(pgn),
            ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"],
        )

    def test_detect_opening_prefers_opening_field(self):
        game = {"opening": "Sicilian Defense", "eco": "https://www.chess.com/openings/Sicilian-Defense"}
        self.assertEqual(cc.detect_opening(game), "Sicilian Defense")

    def test_detect_opening_uses_eco_slug(self):
        game = {"eco": "https://www.chess.com/openings/French-Defense"}
        self.assertEqual(cc.detect_opening(game), "French Defense")

    def test_get_stage_for_ply(self):
        self.assertEqual(cc.get_stage_for_ply(1), "opening")
        self.assertEqual(cc.get_stage_for_ply(25), "midgame")
        self.assertEqual(cc.get_stage_for_ply(80), "endgame")

    def test_review_move_flags_good_and_bad(self):
        tag, reason, _ = cc.review_move("Qh5+", 5)
        self.assertIsNone(tag)
        self.assertIn("applies check", reason)

        tag, _, _ = cc.review_move("Qh5??", 5)
        self.assertEqual(tag, "bad")

        tag, _, _ = cc.review_move("exd8=Q#", 62)
        self.assertEqual(tag, "good")

    def test_get_player_color(self):
        game = {
            "white": {"username": "SampleUser"},
            "black": {"username": "Other"},
        }
        self.assertEqual(cc.get_player_color(game, "SampleUser"), "white")
        self.assertEqual(cc.get_player_color(game, "other"), "black")
        self.assertIsNone(cc.get_player_color(game, "nobody"))

    def test_get_games_sorted_most_recent_first(self):
        archives = ["https://api.chess.com/pub/player/u/games/2026/03"]
        original_fetch = cc.fetch_json

        def fake_fetch_json(_url, timeout=30):  # noqa: ARG001
            return {
                "games": [
                    {"end_time": 100, "id": "old"},
                    {"end_time": 300, "id": "new"},
                    {"end_time": 200, "id": "mid"},
                ]
            }

        cc.fetch_json = fake_fetch_json
        try:
            games = cc.get_games_from_archives(archives, cutoff_epoch=0)
        finally:
            cc.fetch_json = original_fetch

        self.assertEqual([g["id"] for g in games], ["new", "mid", "old"])

    def test_analyze_game_heuristic_shape(self):
        game = {
            "white": {"username": "SampleUser", "result": "win"},
            "black": {"username": "Other", "result": "checkmated"},
            "pgn": """[Event \"Live Chess\"]
[Opening \"Italian Game\"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 1-0
""",
            "url": "https://www.chess.com/game/live/123",
            "time_class": "blitz",
            "rated": True,
            "end_time": 1700000000,
        }
        analyzed = cc.analyze_game_heuristic(game, "SampleUser")
        self.assertEqual(analyzed["opening"], "Italian Game")
        self.assertIn("stage_performance", analyzed)
        self.assertIsNone(analyzed["engine_depth"])


if __name__ == "__main__":
    unittest.main()
