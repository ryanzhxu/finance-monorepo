from __future__ import annotations

from shared.models import AnalyzeRequest, BatchAnalyzeRequest, EntryRequest, ScreenRequest, TrendingScreenRequest


def _example(model_type: type):
    return model_type.model_config["json_schema_extra"]["example"]


def test_request_examples_validate() -> None:
    AnalyzeRequest.model_validate(_example(AnalyzeRequest))
    BatchAnalyzeRequest.model_validate(_example(BatchAnalyzeRequest))
    EntryRequest.model_validate(_example(EntryRequest))
    ScreenRequest.model_validate(_example(ScreenRequest))
    TrendingScreenRequest.model_validate(_example(TrendingScreenRequest))


def test_screen_postman_examples_validate() -> None:
    examples = ScreenRequest.model_config["json_schema_extra"]["x-postman-examples"]
    for payload in examples.values():
        ScreenRequest.model_validate(payload)
