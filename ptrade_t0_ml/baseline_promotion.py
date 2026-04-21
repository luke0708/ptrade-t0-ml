from __future__ import annotations

import argparse
import json
import logging
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .config import CANDIDATE_CONFIG, DEFAULT_CONFIG, ProjectConfig
from .io_utils import atomic_write_json
from .minute_foundation import configure_logging as configure_foundation_logging

LOGGER = logging.getLogger(__name__)


def promote_candidate_to_production(
    production_config: ProjectConfig = DEFAULT_CONFIG,
    candidate_config: ProjectConfig = CANDIDATE_CONFIG,
) -> dict[str, object]:
    if production_config.baseline_model_slot != "production":
        raise ValueError("production_config must use baseline_model_slot='production'.")
    if candidate_config.baseline_model_slot != "candidate":
        raise ValueError("candidate_config must use baseline_model_slot='candidate'.")
    if not candidate_config.baseline_metadata_path.exists():
        raise FileNotFoundError(
            f"Candidate baseline metadata is missing: {candidate_config.baseline_metadata_path}"
        )

    candidate_metadata = json.loads(candidate_config.baseline_metadata_path.read_text(encoding="utf-8"))
    candidate_models_dir = candidate_config.baseline_models_dir
    production_models_dir = production_config.baseline_models_dir
    production_models_dir.mkdir(parents=True, exist_ok=True)

    promoted_metadata = deepcopy(candidate_metadata)
    promoted_metadata["model_slot"] = "production"
    promoted_metadata["promoted_from_model_slot"] = str(candidate_metadata.get("model_slot", "candidate"))
    promoted_metadata["promoted_at"] = datetime.now().isoformat(timespec="seconds")
    promoted_metadata["source_metadata_path"] = str(candidate_config.baseline_metadata_path)
    promoted_metadata["baseline_models_dir"] = str(production_models_dir)
    promoted_metadata["baseline_metadata_path"] = str(production_config.baseline_metadata_path)

    copy_plan: list[tuple[Path, Path, str]] = []
    for head_name, head_payload in promoted_metadata["heads"].items():
        source_model_path = Path(head_payload["model_path"])
        if not source_model_path.exists():
            raise FileNotFoundError(f"Candidate model file is missing for {head_name}: {source_model_path}")
        target_model_path = production_models_dir / source_model_path.name
        copy_plan.append((source_model_path, target_model_path, head_name))

    for existing_file in production_models_dir.glob("*.json"):
        existing_file.unlink()

    for source_model_path, target_model_path, head_name in copy_plan:
        shutil.copy2(source_model_path, target_model_path)
        promoted_metadata["heads"][head_name]["model_path"] = str(target_model_path)

    atomic_write_json(production_config.baseline_metadata_path, promoted_metadata)
    LOGGER.info("Promoted candidate baseline into production: %s", production_config.baseline_metadata_path)
    return {
        "production_metadata_path": str(production_config.baseline_metadata_path),
        "production_models_dir": str(production_models_dir),
        "candidate_metadata_path": str(candidate_config.baseline_metadata_path),
    }


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Promote the current candidate baseline model into production.")


def main() -> None:
    configure_foundation_logging()
    build_parser().parse_args()
    promote_candidate_to_production()


if __name__ == "__main__":
    main()
