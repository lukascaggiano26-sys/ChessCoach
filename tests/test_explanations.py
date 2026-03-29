import unittest

from explanations import (
    build_detailed_explanation,
    build_short_explanation,
    classify_issue_type,
    describe_transition,
)


class ExplanationSnapshotTests(unittest.TestCase):
    def test_short_explanation_snapshot(self):
        actual = build_short_explanation(
            "Mistake",
            "Qh5",
            played_san="Qe2",
            tags=["fork"],
            transition="equal -> losing",
            issue_type="immediate tactic",
        )
        expected = "Mistake: best move was Qh5. Key motif: fork; State change: equal -> losing; Issue: immediate tactic."
        self.assertEqual(actual, expected)

    def test_detailed_explanation_snapshot_fork(self):
        actual = build_detailed_explanation(
            "Mistake",
            "Qh5",
            0.134,
            -182,
            ["fork"],
            played_san="Qe2",
            transition="equal -> losing",
            issue_type="immediate tactic",
            phase="middlegame",
        )
        expected = (
            "Mistake: you played Qe2, while the engine prefers Qh5. "
            "This allowed a fork pattern that created immediate tactical pressure. "
            "Expected-points loss was 0.134 and the evaluation swing was -182 centipawns. "
            "Game-state transition: equal -> losing. "
            "Primary issue type: immediate tactic."
        )
        self.assertEqual(actual, expected)

    def test_detailed_explanation_snapshot_positional(self):
        actual = build_detailed_explanation(
            "Good",
            "Nf3",
            0.031,
            -28,
            [],
            played_san="Nc3",
            transition=None,
            issue_type="strategic inaccuracy",
            phase="opening",
        )
        expected = (
            "Good: you played Nc3, while the engine prefers Nf3. "
            "The main difference was positional quality rather than a single forcing tactic. "
            "Expected-points loss was 0.031 and the evaluation swing was -28 centipawns. "
            "Game state stayed in the same broad bucket, but move quality still mattered. "
            "Primary issue type: strategic inaccuracy."
        )
        self.assertEqual(actual, expected)

    def test_transition_and_issue_helpers(self):
        self.assertEqual(describe_transition(0.50, 0.20), "equal -> losing")
        self.assertEqual(classify_issue_type("Miss", [], -10, "middlegame"), "missed defensive resource")


if __name__ == "__main__":
    unittest.main()
