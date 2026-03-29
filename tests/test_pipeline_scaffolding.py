import unittest

from classify import apply_special_labels, classify_expected_points_loss
from expected_points import expected_points_from_cp
from explanations import build_short_explanation
from models import EngineLine, GameReview, MoveReview


class PipelineScaffoldingTests(unittest.TestCase):
    def test_expected_points_bounds(self):
        self.assertGreaterEqual(expected_points_from_cp(-500, 1200), 0.0)
        self.assertLessEqual(expected_points_from_cp(500, 1200), 1.0)

    def test_classification_and_special_labels(self):
        self.assertEqual(classify_expected_points_loss(0.0), "Best")
        self.assertEqual(classify_expected_points_loss(0.25), "Blunder")
        self.assertEqual(apply_special_labels("Excellent", 0, 200, 0.7, False), "Great")

    def test_dataclass_serialization(self):
        review = MoveReview(
            san="e4",
            uci="e2e4",
            ply=1,
            side="white",
            label="Best",
            expected_points_before=0.5,
            expected_points_after_best=0.52,
            expected_points_after_played=0.52,
            expected_points_loss=0.0,
            best_move_uci="e2e4",
            best_move_san="e4",
            best_pv=["e4", "e5"],
            played_pv=["e4", "e5"],
            tactical_tags=[],
            short_explanation=build_short_explanation("Best", "e4"),
            detailed_explanation="Best move",
            move_number=1,
            move_number_display="1.",
            classification_reason="Best move",
            eval_before_cp=20,
            eval_after_cp=30,
            best_eval_after_cp=30,
        )
        game_review = GameReview(
            url=None,
            time_class="rapid",
            rated=True,
            end_time=0,
            player_color="white",
            player_result="win",
            opening="King's Pawn",
            stage_performance={"opening": {"score": 60, "grade": "C", "sample_size": 1}},
            engine_version="Stockfish 18",
            engine_warning=None,
            engine_depth=12,
            average_eval_delta_cp=10.0,
            reviewed_moves=[review],
            good_moves=[],
            bad_moves=[],
        )
        payload = game_review.to_dict()
        self.assertEqual(payload["reviewed_moves"][0]["uci"], "e2e4")

    def test_engineline_exists(self):
        line = EngineLine(multipv=1, move_uci="e2e4", move_san="e4", score_cp=25)
        self.assertEqual(line.move_san, "e4")


if __name__ == "__main__":
    unittest.main()
