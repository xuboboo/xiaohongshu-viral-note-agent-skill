import pytest

from xhs_skill.core.auth import Principal
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.mcp.protocol import MCPProtocol
from xhs_skill.mcp.tools import MCPToolService
from xhs_skill.research.service import ResearchService
from xhs_skill.search.registry import SearchRegistry


@pytest.mark.asyncio
async def test_mcp_initialize_and_tools_list():
    protocol = MCPProtocol()
    principal = Principal("test", "tenant", frozenset({"*"}), 2, "test")
    init = await protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, principal)
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "xiaohongshu-viral-note-agent-skill"
    tools = await protocol.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, principal)
    assert tools is not None
    assert any(tool["name"] == "search_hot_notes" for tool in tools["result"]["tools"])
    hot = next(t for t in tools["result"]["tools"] if t["name"] == "search_hot_notes")
    assert hot["description"].startswith("[")
    assert hot.get("_meta", {}).get("category") == "research"
    assert tools["result"]["_meta"]["schema"] == "tool_groups.v1"
    assert tools["result"]["_meta"]["groups"]


@pytest.mark.asyncio
async def test_mcp_exposes_complete_operations_loop():
    protocol = MCPProtocol()
    principal = Principal("test", "tenant", frozenset({"*"}), 3, "test")
    tools = await protocol.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, principal
    )
    assert tools is not None
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {
        "sync_published_metrics",
        "get_performance_attribution",
        "get_account_weight_trend",
        "create_content_calendar",
        "create_content_series",
        "create_abn_experiment",
        "assign_experiment_variant",
        "record_experiment_outcome",
        "analyze_abn_experiment",
        "choose_content_bandit",
        "update_content_bandit",
        "search_asset_library",
        "generate_retrospective",
    }.issubset(names)


@pytest.mark.asyncio
async def test_mcp_search_hot_notes_accepts_web_results(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        search_auto_fallback="delegate",
        model_providers_file=tmp_path / "missing.yaml",
        enterprise_enabled=False,
        enterprise_policy_enforcement=False,
    )
    monkeypatch.setattr("xhs_skill.research.service.get_settings", lambda: settings)
    monkeypatch.setattr("xhs_skill.mcp.tools.get_settings", lambda: settings)
    service = MCPToolService()
    service.research = ResearchService(SearchRegistry(settings))
    principal = Principal("test", "tenant", frozenset({"*"}), 2, "test")

    delegated = await service.call(
        "search_hot_notes",
        {"query": "通勤防晒", "limit": 5},
        principal,
    )
    assert delegated["status"] == "needs_web_search"
    assert delegated["suggested_queries"]
    assert delegated["ux"]["status"] == "needs_web_search"
    assert delegated["next_step"]

    report = await service.call(
        "search_hot_notes",
        {
            "query": "通勤防晒",
            "limit": 5,
            "web_results": [
                {
                    "url": "https://www.xiaohongshu.com/explore/mcp-1",
                    "title": "通勤防晒实测",
                    "snippet": "点赞 900",
                }
            ],
        },
        principal,
    )
    assert report["notes"]
    assert "client_web" in report["coverage_warning"]
    assert report["ux"]["schema"] == "tool_ux.v1"
    assert report["next_step"]
