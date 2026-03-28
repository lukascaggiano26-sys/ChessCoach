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

    def test_analyze_game_returns_stage_scores(self):
        game = {
            "white": {"username": "SampleUser", "result": "win"},
            "black": {"username": "Other", "result": "checkmated"},
            "pgn": """[Event \"Live Chess\"]
[Opening \"Italian Game\"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 5. Qh5? Nxh5 6. Bxf7+ Kxf7 1-0
""",
            "url": "https://www.chess.com/game/live/123",
            "time_class": "blitz",
            "rated": True,
            "end_time": 1700000000,
        }

        analyzed = cc.analyze_game(game, "SampleUser")
        self.assertEqual(analyzed["opening"], "Italian Game")
        self.assertIn("stage_performance", analyzed)
        self.assertIn("opening", analyzed["stage_performance"])
        self.assertEqual(analyzed["player_color"], "white")


if __name__ == "__main__":
    unittest.main()
