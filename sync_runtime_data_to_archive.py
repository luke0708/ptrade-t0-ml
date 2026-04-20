from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ptrade_t0_ml.config import DEFAULT_CONFIG, ProjectConfig


def sync_runtime_data_to_archive(config: ProjectConfig = DEFAULT_CONFIG) -> list[Path]:
    archive_dir = config.backup_archive_data_dir
    if archive_dir is None:
        raise ValueError("PTRADE_ARCHIVE_DATA_DIR is not configured; cannot sync runtime data to archive.")

    runtime_dir = config.data_dir
    archive_dir.mkdir(parents=True, exist_ok=True)

    copied_paths: list[Path] = []
    for source_path in runtime_dir.rglob("*"):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(runtime_dir)
        target_path = archive_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied_paths.append(target_path)
    return copied_paths


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Sync local runtime data directory to the optional archive directory.")


def main() -> None:
    build_parser().parse_args()
    copied_paths = sync_runtime_data_to_archive(DEFAULT_CONFIG)
    print(f"Synced {len(copied_paths)} files to archive.")


if __name__ == "__main__":
    main()
