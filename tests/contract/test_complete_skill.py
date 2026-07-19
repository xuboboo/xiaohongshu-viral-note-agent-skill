from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app
from xhs_skill.core.config import Settings
from xhs_skill.mcp.tools import TOOL_DEFINITIONS
from xhs_skill.search import SearchRegistry


def test_complete_mcp_surface():
    names = {item["name"] for item in TOOL_DEFINITIONS}
    assert len(names) >= 20
    assert {
        "search_hot_notes",
        "generate_xhs_note",
        "query_account_weight",
        "start_account_login",
        "create_publish_draft",
        "publish_note",
        "schedule_note",
        "analyze_performance",
    }.issubset(names)
    # 场景前缀 + 分组元数据（Agent 扫工具用）
    hot = next(item for item in TOOL_DEFINITIONS if item["name"] == "search_hot_notes")
    assert hot["description"].startswith("[")
    assert hot.get("_meta", {}).get("category") == "research"
    groups_path = Path(__file__).resolve().parents[2] / "contracts" / "mcp-tool-groups.json"
    if groups_path.exists():
        groups = __import__("json").loads(groups_path.read_text(encoding="utf-8"))
        assert groups.get("schema") == "tool_groups.v1"
        assert groups.get("groups")


def test_a2a_executes_real_research_task(auth_headers):
    client = TestClient(create_app())
    response = client.post(
        "/a2a",
        headers=auth_headers,
        json={
            "jsonrpc": "2.0",
            "id": "a2a-1",
            "method": "message/send",
            "params": {
                "skill_id": "research-hot-notes",
                "arguments": {
                    "query": "防晒",
                    "providers": ["fixture"],
                    "limit": 3,
                },
            },
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["status"]["state"] == "completed"
    assert result["artifacts"][0]["parts"][0]["data"]["notes"]


def test_search_registry_registers_configured_providers(tmp_path: Path):
    settings = Settings(
        app_secret_key="x" * 40,
        brave_search_api_key="brave",
        bing_search_api_key="bing",
        google_search_api_key="google",
        google_search_cx="cx",
        searxng_base_url="https://search.example.test",
        model_providers_file=tmp_path / "missing.yaml",
    )
    providers = SearchRegistry(settings).list()
    assert {"fixture", "client_web", "brave", "bing", "google_cse", "searxng"}.issubset(providers)
