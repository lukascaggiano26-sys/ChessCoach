import unittest

from classify import assign_move_label, classify_expected_points_loss


class ClassifyTests(unittest.TestCase):
    def test_ordinary_bands_exact(self):
        self.assertEqual(classify_expected_points_loss(0.0), "Best")
        self.assertEqual(classify_expected_points_loss(0.01), "Excellent")
        self.assertEqual(classify_expected_points_loss(0.02), "Excellent")
        self.assertEqual(classify_expected_points_loss(0.021), "Good")
        self.assertEqual(classify_expected_points_loss(0.05), "Good")
        self.assertEqual(classify_expected_points_loss(0.051), "Inaccuracy")
        self.assertEqual(classify_expected_points_loss(0.10), "Inaccuracy")
        self.assertEqual(classify_expected_points_loss(0.101), "Mistake")
        self.assertEqual(classify_expected_points_loss(0.20), "Mistake")
        self.assertEqual(classify_expected_points_loss(0.201), "Blunder")

    def test_precedence_book(self):
        label, ev = assign_move_label(expected_points_loss=0.9, is_book=True, near_best=False)
        self.assertEqual(label, "Book")
        self.assertEqual(ev["trigger"], "opening_book")

    def test_precedence_brilliant_over_great_and_miss(self):
        label, ev = assign_move_label(
            expected_points_loss=0.15,
            near_best=True,
            sound_sacrifice=True,
            trivially_winning_before=False,
            obvious_recapture=False,
            only_move_save=True,
            missed_forced_mate=True,
        )
        self.assertEqual(label, "Brilliant")
        self.assertEqual(ev["trigger"], "sound_near_best_sacrifice")

    def test_precedence_great_over_miss(self):
        label, ev = assign_move_label(
            expected_points_loss=0.25,
            near_best=True,
            only_move_equalize=True,
            missed_large_material_win=True,
        )
        self.assertEqual(label, "Great")
        self.assertEqual(ev["trigger"], "near_best_state_change")

    def test_miss_trigger(self):
        label, ev = assign_move_label(
            expected_points_loss=0.12,
            near_best=False,
            missed_transition_to_winning=True,
        )
        self.assertEqual(label, "Miss")
        self.assertEqual(ev["trigger"], "missed_opportunity")

    def test_brilliant_exclusions(self):
        label, _ = assign_move_label(
            expected_points_loss=0.0,
            near_best=True,
            sound_sacrifice=True,
            trivially_winning_before=True,
        )
        self.assertNotEqual(label, "Brilliant")

        label, _ = assign_move_label(
            expected_points_loss=0.0,
            near_best=True,
            sound_sacrifice=True,
            obvious_recapture=True,
        )
        self.assertNotEqual(label, "Brilliant")

    def test_evidence_shape(self):
        label, ev = assign_move_label(expected_points_loss=0.03)
        self.assertEqual(label, "Good")
        self.assertIn("flags", ev)
        self.assertIn("band", ev)
        self.assertIn("ordinary_label", ev)


if __name__ == "__main__":
    unittest.main()
