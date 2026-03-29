import unittest

from expected_points import expected_points_loss, score_to_expected_points


class ExpectedPointsTests(unittest.TestCase):
    def test_cp_scores_monotonic(self):
        self.assertLess(score_to_expected_points(-200, ply=20), score_to_expected_points(0, ply=20))
        self.assertLess(score_to_expected_points(0, ply=20), score_to_expected_points(200, ply=20))

    def test_extreme_cp_scores(self):
        self.assertGreater(score_to_expected_points(900, ply=20), 0.9)
        self.assertLess(score_to_expected_points(-900, ply=20), 0.1)

    def test_python_chess_mate_scores_if_available(self):
        try:
            import chess.engine as ce
        except Exception:
            self.skipTest("python-chess not installed in test environment")

        mate_win = ce.Mate(3)
        mate_loss = ce.Mate(-3)
        win_ep = score_to_expected_points(mate_win, ply=30)
        loss_ep = score_to_expected_points(mate_loss, ply=30)
        self.assertGreater(win_ep, 0.95)
        self.assertLess(loss_ep, 0.05)

    def test_expected_points_loss_non_negative(self):
        self.assertGreaterEqual(expected_points_loss(100, -100, ply=20), 0.0)
        self.assertEqual(expected_points_loss(-100, 100, ply=20), 0.0)


if __name__ == "__main__":
    unittest.main()
