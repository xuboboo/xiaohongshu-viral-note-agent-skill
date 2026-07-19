from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app


def test_health_and_agent_card(auth_headers):
    client = TestClient(create_app())
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/health/diagnostics").status_code == 401
    assert client.get("/health/diagnostics", headers=auth_headers).status_code == 200
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers=auth_headers).status_code == 200
    card = client.get("/.well-known/agent-card.json", headers=auth_headers)
    assert card.status_code == 200
    body = card.json()
    assert body["name"] == "小红书爆款笔记生成 agent Skill"
    skills = body.get("skills") or []
    assert skills
    assert any("[" in (s.get("description") or "") for s in skills)
    assert any(s.get("tags") for s in skills)


def test_fixture_research_endpoint(auth_headers):
    client = TestClient(create_app())
    response = client.post(
        "/v1/research/hot-notes",
        json={"query": "防晒", "time_range": "7d", "limit": 5, "sources": ["fixture"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"]
    assert response.json()["coverage_warning"]
