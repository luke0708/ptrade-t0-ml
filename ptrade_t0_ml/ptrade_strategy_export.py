from __future__ import annotations

import ast
import json
import logging
from pprint import pformat
from typing import Any

from .config import DEFAULT_CONFIG, ProjectConfig
from .io_utils import atomic_write_text

LOGGER = logging.getLogger(__name__)

ML_SIGNAL_VARIABLE_NAME = "ML_SIGNAL_PAYLOAD"


def _offset_for_position(source: str, lineno: int, col_offset: int) -> int:
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[: lineno - 1]) + col_offset


def _locate_signal_assignment_span(template_source: str) -> tuple[int, int]:
    module = ast.parse(template_source)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == ML_SIGNAL_VARIABLE_NAME:
                start = _offset_for_position(template_source, node.lineno, node.col_offset)
                end = _offset_for_position(template_source, node.end_lineno, node.end_col_offset)
                return start, end
    raise ValueError(f"Could not find {ML_SIGNAL_VARIABLE_NAME} assignment in template.")


def _render_signal_assignment(signal_payload: dict[str, Any]) -> str:
    return f"{ML_SIGNAL_VARIABLE_NAME} = {pformat(signal_payload, sort_dicts=False, width=100)}"


def render_ptrade_strategy_source(
    template_source: str,
    signal_payload: dict[str, Any],
) -> str:
    start, end = _locate_signal_assignment_span(template_source)
    assignment = _render_signal_assignment(signal_payload)
    return f"{template_source[:start]}{assignment}{template_source[end:]}"


def _load_signal_payload(config: ProjectConfig) -> dict[str, Any]:
    if not config.ml_daily_signal_json_path.exists():
        LOGGER.info("ML daily signal missing. Exporting signal first.")
        from .signal_export import build_ml_daily_signal

        return build_ml_daily_signal(config)
    return json.loads(config.ml_daily_signal_json_path.read_text(encoding="utf-8"))


def export_ptrade_strategy(
    config: ProjectConfig = DEFAULT_CONFIG,
    signal_payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    if signal_payload is None:
        signal_payload = _load_signal_payload(config)

    if not config.ptrade_strategy_template_path.exists():
        raise FileNotFoundError(
            f"PTrade strategy template not found: {config.ptrade_strategy_template_path}"
        )

    signal_for_date = str(signal_payload.get("signal_for_date", "")).strip()
    if not signal_for_date:
        raise ValueError("Signal payload is missing signal_for_date; cannot build dated PTrade script.")

    template_source = config.ptrade_strategy_template_path.read_text(encoding="utf-8")
    rendered_source = render_ptrade_strategy_source(template_source, signal_payload)

    dated_path = config.ptrade_strategy_dated_path(signal_for_date)
    latest_path = config.ptrade_strategy_latest_path

    atomic_write_text(dated_path, rendered_source)
    atomic_write_text(latest_path, rendered_source)

    LOGGER.info("Saved dated PTrade strategy to: %s", dated_path)
    LOGGER.info("Updated latest PTrade strategy to: %s", latest_path)

    return {
        "dated_path": str(dated_path),
        "latest_path": str(latest_path),
        "signal_for_date": signal_for_date,
    }
