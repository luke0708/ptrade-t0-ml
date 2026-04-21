import json
import tempfile
import unittest
from pathlib import Path

from ptrade_t0_ml.baseline_promotion import promote_candidate_to_production
from ptrade_t0_ml.config import ProjectConfig


class BaselinePromotionTests(unittest.TestCase):
    def test_project_config_separates_candidate_and_production_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            base_dir = Path(temp_dir_str)
            production_config = ProjectConfig(base_dir=base_dir, baseline_model_slot="production")
            candidate_config = ProjectConfig(base_dir=base_dir, baseline_model_slot="candidate")

            self.assertNotEqual(production_config.baseline_models_dir, candidate_config.baseline_models_dir)
            self.assertEqual(production_config.baseline_models_dir.name, "baseline_stock_only")
            self.assertEqual(candidate_config.baseline_models_dir.name, "baseline_candidate")

    def test_promote_candidate_to_production_updates_metadata_model_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            base_dir = Path(temp_dir_str)
            production_config = ProjectConfig(base_dir=base_dir, baseline_model_slot="production")
            candidate_config = ProjectConfig(base_dir=base_dir, baseline_model_slot="candidate")
            candidate_config.baseline_models_dir.mkdir(parents=True, exist_ok=True)

            head_names = ["upside_regression", "positive_grid_day_classifier"]
            heads = {}
            for head_name in head_names:
                model_path = candidate_config.baseline_models_dir / f"{head_name}.json"
                model_path.write_text('{"dummy": true}', encoding="utf-8")
                heads[head_name] = {
                    "model_path": str(model_path),
                    "target_column": "target_dummy",
                    "metrics": {},
                }

            candidate_metadata = {
                "trained_at": "2026-04-21T10:00:00",
                "model_slot": "candidate",
                "feature_columns": ["feature_a"],
                "feature_column_count": 1,
                "training_rows": 10,
                "train_rows": 8,
                "test_rows": 2,
                "classifier_train_rows": 6,
                "classifier_validation_rows": 2,
                "test_start_date": "2026-04-01",
                "test_end_date": "2026-04-10",
                "heads": heads,
            }
            candidate_config.baseline_metadata_path.write_text(
                json.dumps(candidate_metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = promote_candidate_to_production(
                production_config=production_config,
                candidate_config=candidate_config,
            )

            production_metadata_path = Path(result["production_metadata_path"])
            self.assertTrue(production_metadata_path.exists())
            production_metadata = json.loads(production_metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(production_metadata["model_slot"], "production")
            self.assertEqual(production_metadata["promoted_from_model_slot"], "candidate")
            self.assertEqual(production_metadata["source_metadata_path"], str(candidate_config.baseline_metadata_path))

            for head_name in head_names:
                promoted_model_path = Path(production_metadata["heads"][head_name]["model_path"])
                self.assertTrue(promoted_model_path.exists())
                self.assertEqual(promoted_model_path.parent, production_config.baseline_models_dir)


if __name__ == "__main__":
    unittest.main()
