from __future__ import annotations

import json

from tools.record_forecast_experiment import _load_champion


def test_load_champion_accepts_the_tool_output_wrapper(tmp_path) -> None:
    wrapped = {"experiment": {"schema_version": "forecast_experiment_manifest_v1", "name": "champion"}}
    path = tmp_path / "champion.json"
    path.write_text(json.dumps(wrapped), encoding="utf-8")

    assert _load_champion(path) == wrapped["experiment"]


def test_load_champion_accepts_a_raw_manifest(tmp_path) -> None:
    raw = {"schema_version": "forecast_experiment_manifest_v1", "name": "champion"}
    path = tmp_path / "champion.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert _load_champion(path) == raw
