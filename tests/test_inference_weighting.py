from __future__ import annotations

import unittest

from carvaluator_scraper.inference import compute_weighted_model_prediction


class WeightedPredictionTests(unittest.TestCase):
    def test_voting_ensemble_is_reported_but_not_weighted_again(self) -> None:
        estimates = [
            {"model": "ridge", "predicted_price_eur": 10_000, "mae": 1_000},
            {"model": "svr_rbf", "predicted_price_eur": 20_000, "mae": 1_000},
            {"model": "voting_ensemble", "predicted_price_eur": 100_000, "mae": 100},
        ]

        prediction = compute_weighted_model_prediction(
            estimates,
            ensemble_method="inverse_mae",
        )

        self.assertEqual(prediction, 15_000)
        voting = next(item for item in estimates if item["model"] == "voting_ensemble")
        self.assertTrue(voting["excluded_from_weighted_average"])
        self.assertEqual(voting["exclusion_reason"], "prevents_double_counting")
        self.assertNotIn("ensemble_weight", voting)
        self.assertNotIn("agreement_weight", voting)


if __name__ == "__main__":
    unittest.main()
