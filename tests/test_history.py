from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from carvaluator_scraper.auth import (
    create_user,
    get_prediction_history_detail,
    initialize_auth_db,
    list_prediction_history,
    record_prediction_history,
)


class PredictionHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "history.db"
        self.env = patch.dict(os.environ, {"CARVALUATOR_AUTH_DB": str(self.db_path)})
        self.env.start()
        initialize_auth_db()
        self.user = create_user(
            email="history@example.com",
            username="history_user",
            password="temporary-password",
        )
        self.other_user = create_user(
            email="other@example.com",
            username="other_user",
            password="temporary-password",
        )

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_full_prediction_report_is_preserved(self) -> None:
        prediction = {
            "source": "autovit",
            "url": "https://www.autovit.ro/autoturisme/anunt/test.html",
            "title": "Masina de test",
            "image_url": "https://example.com/car.jpg",
            "actual_price_eur": 15000,
            "predicted_price_eur": 14250,
            "verdict": "fair",
            "model_name": "weighted_average",
            "delta_percent": 5.26,
            "threshold_percent": 10,
            "normalized_listing": {"make": "Test", "model": "Car"},
            "similar_listings": [{"title": "Masina similara", "price_eur": 14500}],
            "model_estimates": [
                {
                    "model": "weighted_average",
                    "predicted_price_eur": 14250,
                    "weighting": "inverse_mae_with_agreement",
                },
                {"model": "ridge", "predicted_price_eur": 14000, "mae": 2500},
            ],
        }

        item = record_prediction_history(user_id=self.user.id, prediction=prediction)
        summary = list_prediction_history(user_id=self.user.id)[0]
        detail = get_prediction_history_detail(user_id=self.user.id, history_id=item.id)

        self.assertEqual(summary.threshold_percent, 10)
        self.assertEqual(summary.ensemble_method, "inverse_mae_with_agreement")
        self.assertEqual(summary.similar_count, 1)
        self.assertEqual(detail["similar_listings"], prediction["similar_listings"])
        self.assertEqual(detail["model_estimates"], prediction["model_estimates"])
        self.assertEqual(detail["history_id"], item.id)

    def test_history_detail_is_isolated_by_account(self) -> None:
        item = record_prediction_history(
            user_id=self.user.id,
            prediction={
                "title": "Privat",
                "predicted_price_eur": 10000,
                "similar_listings": [],
                "model_estimates": [],
            },
        )

        detail = get_prediction_history_detail(user_id=self.other_user.id, history_id=item.id)
        self.assertIsNone(detail)


if __name__ == "__main__":
    unittest.main()
