from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
POSTMAN_DIR = ROOT / "postman"
COLLECTION_NAME_BY_SERVICE = {
    "analyst": "finance-monorepo analyst",
    "screener": "finance-monorepo screener",
}
BASE_URL_VAR_BY_SERVICE = {
    "analyst": "analyst_base_url",
    "screener": "screener_base_url",
}
EXAMPLE_KEY_BY_OPERATION = {
    ("POST", "/screen/undervalued"): "undervalued",
    ("POST", "/screen/custom"): "custom",
    ("POST", "/screen/opportunities"): "opportunities",
    ("POST", "/screen/watchlist"): "watchlist",
}
PROD_CROSS_SERVICE_CHECK_NAME = "Prod Cross-Service Check"
PROD_CROSS_SERVICE_CHECK_BODY = {
    "universe": "SP500",
    "limit": 3,
    "horizon": "2-4W",
    "include_analysis": True,
    "include_narrative": False,
}
PROD_CROSS_SERVICE_CHECK_TEST = """pm.test("status is 200", function () {
  pm.response.to.have.status(200);
});

const payload = pm.response.json();

pm.test("screen type is opportunities", function () {
  pm.expect(payload.screen_type).to.eql("opportunities");
});

pm.test("results are present", function () {
  pm.expect(payload.results).to.be.an("array").that.is.not.empty;
});

const first = payload.results[0] || {};

pm.test("score breakdown is attached", function () {
  pm.expect(first.score_breakdown).to.be.an("object");
});

pm.test("trend booster is included", function () {
  pm.expect(first.score_breakdown).to.have.property("trend_booster");
});

pm.test("data quality fields are present", function () {
  pm.expect(first).to.have.property("data_quality_score");
  pm.expect(first).to.have.property("data_freshness");
});

pm.test("analyst attachment is present", function () {
  pm.expect(first.entry_assessment).to.be.a("string");
});

pm.test("analyst degradation did not trigger", function () {
  pm.expect(typeof first.reason === "string" && first.reason.includes("Analyst unavailable")).to.eql(false);
});"""


def load_openapi(service: str) -> dict[str, Any]:
    with (OPENAPI_DIR / f"{service}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_ref(document: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = document
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


def schema_for_operation(document: dict[str, Any], method: str, path: str) -> dict[str, Any] | None:
    operation = document.get("paths", {}).get(path, {}).get(method.lower())
    if not operation:
        return None
    content = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = content.get("schema")
    if not schema:
        return None
    if "$ref" in schema:
        return resolve_ref(document, schema["$ref"])
    return schema


def example_for_operation(document: dict[str, Any], method: str, path: str) -> dict[str, Any] | None:
    schema = schema_for_operation(document, method, path)
    if not schema:
        return None

    named_examples = schema.get("x-postman-examples", {})
    if named_examples:
        example_key = EXAMPLE_KEY_BY_OPERATION.get((method.upper(), path))
        if example_key and example_key in named_examples:
            return deepcopy(named_examples[example_key])

    example = schema.get("example")
    if isinstance(example, dict):
        return deepcopy(example)

    examples = schema.get("examples")
    if isinstance(examples, list):
        for candidate in examples:
            if isinstance(candidate, dict):
                return deepcopy(candidate)
    return None


def collection_output_path(service: str) -> Path:
    return POSTMAN_DIR / f"{service}.postman_collection.json"


def run_converter(service: str) -> None:
    source = OPENAPI_DIR / f"{service}.json"
    target = collection_output_path(service)
    POSTMAN_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        "npx",
        "-y",
        "openapi-to-postmanv2",
        "-s",
        str(source),
        "-o",
        str(target),
        "-p",
        "-O",
        "requestNameSource=Fallback",
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def iter_request_items(items: list[dict[str, Any]]):
    for item in items:
        if "request" in item:
            yield item
        if "item" in item:
            yield from iter_request_items(item["item"])


def path_from_request(item: dict[str, Any]) -> str:
    url = item["request"]["url"]
    path = url.get("path") or []
    if isinstance(path, list):
        return "/" + "/".join(segment.strip("/") for segment in path if segment)
    raw = url.get("raw", "")
    return "/" + raw.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0].lstrip("/")


def normalize_request_urls(collection: dict[str, Any], base_url_var: str) -> None:
    for item in iter_request_items(collection.get("item", [])):
        request = item["request"]
        url = request["url"]
        path = path_from_request(item)
        query = url.get("query") or []
        raw = f"{{{{{base_url_var}}}}}{path}"
        if query:
            raw = raw + "?" + "&".join(f"{part['key']}={part.get('value', '')}" for part in query if part.get("key"))
        url["raw"] = raw
        url["host"] = [f"{{{{{base_url_var}}}}}"]
        url["path"] = [segment for segment in path.split("/") if segment]


def ensure_json_bodies(service: str, collection: dict[str, Any], document: dict[str, Any]) -> None:
    for item in iter_request_items(collection.get("item", [])):
        request = item["request"]
        method = request.get("method", "GET").upper()
        path = path_from_request(item)
        example = example_for_operation(document, method, path)
        if not example:
            continue

        request["header"] = [header for header in request.get("header", []) if header.get("key", "").lower() != "content-type"]
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(example, indent=2),
            "options": {"raw": {"language": "json"}},
        }


def normalize_collection(service: str) -> None:
    document = load_openapi(service)
    path = collection_output_path(service)
    with path.open(encoding="utf-8") as handle:
        collection = json.load(handle)

    collection["info"].pop("_postman_id", None)
    collection["info"]["name"] = COLLECTION_NAME_BY_SERVICE[service]
    collection.pop("variable", None)

    normalize_request_urls(collection, BASE_URL_VAR_BY_SERVICE[service])
    ensure_json_bodies(service, collection, document)
    if service == "screener":
        upsert_prod_cross_service_check(collection)

    path.write_text(json.dumps(collection, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert_prod_cross_service_check(collection: dict[str, Any]) -> None:
    items = collection.setdefault("item", [])
    items[:] = [item for item in items if item.get("name") != PROD_CROSS_SERVICE_CHECK_NAME]
    items.append(
        {
            "name": PROD_CROSS_SERVICE_CHECK_NAME,
            "event": [
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": PROD_CROSS_SERVICE_CHECK_TEST.splitlines(),
                    },
                }
            ],
            "request": {
                "method": "POST",
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "body": {
                    "mode": "raw",
                    "raw": json.dumps(PROD_CROSS_SERVICE_CHECK_BODY, indent=2),
                    "options": {"raw": {"language": "json"}},
                },
                "url": {
                    "raw": "{{screener_base_url}}/screen/opportunities",
                    "host": ["{{screener_base_url}}"],
                    "path": ["screen", "opportunities"],
                },
                "description": (
                    "Verifies the deployed screener can return opportunity results with "
                    "live analyst attachment over the network."
                ),
            },
            "response": [],
        }
    )


def write_local_environment() -> None:
    POSTMAN_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "finance-monorepo local",
        "values": [
            {
                "key": "analyst_base_url",
                "value": "http://localhost:8001",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "screener_base_url",
                "value": "http://localhost:8002",
                "type": "default",
                "enabled": True,
            },
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "finance-monorepo",
    }
    target = POSTMAN_DIR / "local.postman_environment.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_dev_environment() -> None:
    POSTMAN_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "finance-monorepo edge",
        "values": [
            {
                "key": "analyst_base_url",
                "value": "https://finance-api-dev.rxlab.workers.dev",
                "type": "default",
                "enabled": True,
            },
            {
                "key": "screener_base_url",
                "value": "https://finance-api-dev.rxlab.workers.dev",
                "type": "default",
                "enabled": True,
            },
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "finance-monorepo",
    }
    target = POSTMAN_DIR / "dev.postman_environment.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    subprocess.run([sys.executable, "tools/dump_openapi.py"], check=True, cwd=ROOT)
    for service in ("analyst", "screener"):
        run_converter(service)
        normalize_collection(service)
    write_local_environment()
    write_dev_environment()


if __name__ == "__main__":
    main()
