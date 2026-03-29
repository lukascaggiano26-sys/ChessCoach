import unittest


class MotifTests(unittest.TestCase):
    def setUp(self):
        try:
            import chess
        except Exception:
            self.skipTest("python-chess not installed in test environment")
        self.chess = chess

    def _run(self, keyword: str):
        from motifs import detect_tactical_tags

        board_before = self.chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        move = self.chess.Move.from_uci("e2e4")
        board_after_played = board_before.copy()
        board_after_played.push(move)

        best_move = self.chess.Move.from_uci("d2d4")
        board_after_best = board_before.copy()
        board_after_best.push(best_move)

        motifs = detect_tactical_tags(
            board_before=board_before,
            board_after_played=board_after_played,
            board_after_best=board_after_best,
            played_pv=[keyword],
            best_pv=["quiet"],
            move=move,
            mover_color=self.chess.WHITE,
            chess=self.chess,
        )
        return {m["tag"] for m in motifs}

    def test_all_required_motifs_have_detector_path(self):
        mapping = {
            "fork": "fork",
            "pin": "pin",
            "skewer": "skewer",
            "discovered attack": "discovered attack",
            "discovered check": "discovered check",
            "double attack": "double attack",
            "removal of defender": "removal of defender",
            "deflection": "deflection",
            "decoy": "decoy",
            "interference": "interference",
            "overload": "overload",
            "clearance": "clearance",
            "back-rank tactic": "back-rank tactic",
            "trapped piece": "trapped piece",
            "zwischenzug": "zwischenzug",
            "promotion tactic": "promotion tactic",
            "perpetual-check resource": "perpetual-check resource",
            "exchange sacrifice": "exchange sacrifice",
            "desperado": "desperado",
            "mate threat": "mate threat",
            "hanging piece": "hanging piece",
        }
        for motif, keyword in mapping.items():
            with self.subTest(motif=motif):
                tags = self._run(keyword)
                self.assertIn(motif, tags)


if __name__ == "__main__":
    unittest.main()
