from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pandas as pd


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_dataframe(df: pd.DataFrame, path: Path) -> None:
    ensure_parent_dir(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def atomic_write_text(path: Path, content: str) -> None:
    ensure_parent_dir(path)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(path)
    except PermissionError:
        path.write_text(content, encoding="utf-8")
        for _ in range(5):
            with contextlib.suppress(FileNotFoundError, PermissionError):
                temp_path.unlink()
            if not temp_path.exists():
                break
            time.sleep(0.1)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
