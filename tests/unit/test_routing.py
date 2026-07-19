from xhs_skill.orchestrator.router import route_task
from xhs_skill.schemas.common import TaskMode


def test_routes_publish_as_high_risk():
    result = route_task("帮我自动发布小红书笔记")
    assert result["primary_mode"] == TaskMode.PUBLISH_NOTE
    assert result["risk_level"] == "HIGH"
