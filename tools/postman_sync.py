from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
POSTMAN_DIR = ROOT / "postman"
API_BASE_URL = "https://api.getpostman.com"
DEFAULT_WORKSPACE_NAME = "My Workspace"


def print_missing_key_instructions() -> None:
    print("POSTMAN_API_KEY is not set.")
    print("1. Create a Postman API key in Postman: Settings > Account settings > API keys.")
    print("2. Export it in your shell: export POSTMAN_API_KEY='pmak-...'.")
    print("3. Optional: export POSTMAN_WORKSPACE_ID='your-workspace-id' to target a non-default workspace.")
    print("4. Run: make postman-push")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def environment_payload(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": document["name"],
        "values": document["values"],
    }


class PostmanClient:
    def __init__(self, api_key: str) -> None:
        self.client = httpx.Client(
            base_url=API_BASE_URL,
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.request("GET", "/workspaces").get("workspaces", [])

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return self.request("GET", f"/workspaces/{workspace_id}").get("workspace", {})

    def get_collection(self, uid: str) -> dict[str, Any]:
        return self.request("GET", f"/collections/{uid}").get("collection", {})

    def get_environment(self, uid: str) -> dict[str, Any]:
        return self.request("GET", f"/environments/{uid}").get("environment", {})

    def create_collection(self, workspace_id: str, collection: dict[str, Any]) -> str:
        payload = self.request("POST", f"/collections?workspace={workspace_id}", json={"collection": collection})
        return payload["collection"]["uid"]

    def update_collection(self, uid: str, collection: dict[str, Any]) -> None:
        self.request("PUT", f"/collections/{uid}", json={"collection": collection})

    def create_environment(self, workspace_id: str, environment: dict[str, Any]) -> str:
        payload = self.request("POST", f"/environments?workspace={workspace_id}", json={"environment": environment})
        return payload["environment"]["uid"]

    def update_environment(self, uid: str, environment: dict[str, Any]) -> None:
        self.request("PUT", f"/environments/{uid}", json={"environment": environment})

    def close(self) -> None:
        self.client.close()


def resolve_workspace_id(client: PostmanClient) -> str:
    explicit = os.getenv("POSTMAN_WORKSPACE_ID")
    if explicit:
        return explicit

    workspaces = client.list_workspaces()
    for workspace in workspaces:
        if workspace.get("name") == DEFAULT_WORKSPACE_NAME:
            return workspace["id"]
    raise RuntimeError(
        f"Could not find a workspace named '{DEFAULT_WORKSPACE_NAME}'. "
        "Set POSTMAN_WORKSPACE_ID to the target workspace id and rerun make postman-push."
    )


def upsert_collection(client: PostmanClient, workspace_id: str, path: Path) -> None:
    collection = load_json(path)
    name = collection["info"]["name"]
    workspace = client.get_workspace(workspace_id)
    existing_uid = None
    for reference in workspace.get("collections", []):
        candidate = client.get_collection(reference["uid"])
        if candidate.get("info", {}).get("name") == name:
            existing_uid = reference["uid"]
            break

    if existing_uid:
        client.update_collection(existing_uid, collection)
        print(f"Updated collection: {name}")
    else:
        client.create_collection(workspace_id, collection)
        print(f"Created collection: {name}")


def upsert_environment(client: PostmanClient, workspace_id: str, path: Path) -> None:
    environment = environment_payload(load_json(path))
    name = environment["name"]
    workspace = client.get_workspace(workspace_id)
    existing_uid = None
    for reference in workspace.get("environments", []):
        candidate = client.get_environment(reference["uid"])
        if candidate.get("name") == name:
            existing_uid = reference["uid"]
            break

    if existing_uid:
        client.update_environment(existing_uid, environment)
        print(f"Updated environment: {name}")
    else:
        client.create_environment(workspace_id, environment)
        print(f"Created environment: {name}")


def main() -> int:
    api_key = os.getenv("POSTMAN_API_KEY")
    if not api_key:
        print_missing_key_instructions()
        return 0

    client = PostmanClient(api_key)
    try:
        workspace_id = resolve_workspace_id(client)
        upsert_collection(client, workspace_id, POSTMAN_DIR / "analyst.postman_collection.json")
        upsert_collection(client, workspace_id, POSTMAN_DIR / "screener.postman_collection.json")
        upsert_environment(client, workspace_id, POSTMAN_DIR / "local.postman_environment.json")
        upsert_environment(client, workspace_id, POSTMAN_DIR / "dev.postman_environment.json")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        print(f"Postman API request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise SystemExit(1) from exc
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
