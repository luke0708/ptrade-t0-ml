import tempfile
import unittest
from pathlib import Path

from ptrade_t0_ml.config import ProjectConfig
from ptrade_t0_ml.ptrade_strategy_export import (
    export_ptrade_strategy,
    render_ptrade_strategy_source,
)


class PTradeStrategyExportTests(unittest.TestCase):
    def test_render_ptrade_strategy_source_replaces_embedded_signal_payload(self) -> None:
        template_source = (
            '"""template"""\n'
            "ML_SIGNAL_PAYLOAD = {\n"
            '    "signal_for_date": "2026-04-20",\n'
            '    "recommended_mode": "SAFE",\n'
            "}\n"
            "\n"
            "def initialize(context):\n"
            "    g.ml_signal = ML_SIGNAL_PAYLOAD\n"
        )
        signal_payload = {
            "date": "2026-04-20",
            "signal_for_date": "2026-04-21",
            "recommended_mode": "NORMAL",
            "position_scale": 0.85,
        }

        rendered = render_ptrade_strategy_source(template_source, signal_payload)

        self.assertIn("'signal_for_date': '2026-04-21'", rendered)
        self.assertIn("'recommended_mode': 'NORMAL'", rendered)
        self.assertIn("def initialize(context):", rendered)
        self.assertNotIn("'signal_for_date': '2026-04-20'", rendered)

    def test_export_ptrade_strategy_writes_dated_and_latest_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            data_dir = temp_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            template_path = data_dir / "ptrade_300661.py"
            template_path.write_text(
                '"""template"""\n'
                "ML_SIGNAL_PAYLOAD = {\n"
                '    "signal_for_date": "2026-04-20",\n'
                '    "recommended_mode": "SAFE",\n'
                "}\n"
                "\n"
                "def initialize(context):\n"
                "    g.ml_signal = ML_SIGNAL_PAYLOAD\n",
                encoding="utf-8",
            )
            config = ProjectConfig(base_dir=temp_dir)
            signal_payload = {
                "date": "2026-04-20",
                "signal_for_date": "2026-04-21",
                "recommended_mode": "NORMAL",
                "position_scale": 0.85,
                "grid_width_scale": 1.0,
            }

            result = export_ptrade_strategy(config, signal_payload)

            dated_path = Path(result["dated_path"])
            latest_path = Path(result["latest_path"])
            self.assertEqual(dated_path.name, "ptrade_300661_20260421.py")
            self.assertTrue(dated_path.exists())
            self.assertTrue(latest_path.exists())
            rendered = dated_path.read_text(encoding="utf-8")
            self.assertIn("'signal_for_date': '2026-04-21'", rendered)
            self.assertIn("'position_scale': 0.85", rendered)
            self.assertIn("g.ml_signal = ML_SIGNAL_PAYLOAD", rendered)


if __name__ == "__main__":
    unittest.main()
