from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app


def test_operations_api_end_to_end(auth_headers: dict[str, str]) -> None:
    suffix = uuid4().hex[:12]
    account_id = f"account-{suffix}"
    note_id = f"note-{suffix}"
    with TestClient(create_app()) as client:
        for index, views in enumerate((800, 1200)):
            response = client.post(
                "/v1/operations/metrics/sync",
                headers=auth_headers,
                json={
                    "note_id": note_id if index else f"baseline-{suffix}",
                    "account_id": account_id,
                    "views": views,
                    "likes": 40 + index * 20,
                    "saves": 15 + index * 10,
                    "comments": 5 + index,
                    "shares": 3 + index,
                    "content_features": {"topic": "防晒", "title_number": float(index)},
                },
            )
            assert response.status_code == 200, response.text

        attribution = client.get(
            f"/v1/operations/accounts/{account_id}/notes/{note_id}/attribution",
            headers=auth_headers,
        )
        assert attribution.status_code == 200, attribution.text
        assert attribution.json()["note_id"] == note_id
        assert "caveat" in attribution.json()

        calendar = client.post(
            "/v1/operations/calendar",
            headers=auth_headers,
            json={
                "account_id": account_id,
                "topics": ["通勤防晒", "敏感肌"],
                "days": 14,
                "posts_per_week": 3,
            },
        )
        assert calendar.status_code == 200, calendar.text
        assert calendar.json()["items"]

        series = client.post(
            "/v1/operations/series",
            headers=auth_headers,
            json={
                "account_id": account_id,
                "title": "通勤防晒系列",
                "topic": "通勤防晒",
                "audience": "上班族",
                "episode_count": 4,
            },
        )
        assert series.status_code == 200, series.text
        assert len(series.json()["episodes"]) == 4

        experiment = client.post(
            "/v1/operations/experiments",
            headers=auth_headers,
            json={
                "account_id": account_id,
                "name": "标题 A/B/n",
                "hypothesis": "清单标题提高收藏率",
                "primary_metric": "save_rate",
                "variants": [
                    {"id": "control", "name": "问题型", "payload": {}, "allocation": 1},
                    {"id": "list", "name": "清单型", "payload": {}, "allocation": 1},
                ],
            },
        )
        assert experiment.status_code == 200, experiment.text
        experiment_id = experiment.json()["id"]
        assignment = client.post(
            f"/v1/operations/experiments/{experiment_id}/assign",
            headers=auth_headers,
            json={"subject_id": f"subject-{suffix}"},
        )
        assert assignment.status_code == 200, assignment.text
        assert assignment.json()["variant_id"] in {"control", "list"}

        for index in range(2):
            for variant, value in (("control", 0.02), ("list", 0.05)):
                outcome = client.post(
                    "/v1/operations/experiments/outcomes",
                    headers=auth_headers,
                    json={
                        "experiment_id": experiment_id,
                        "subject_id": f"{variant}-{suffix}-{index}",
                        "variant_id": variant,
                        "metric": "save_rate",
                        "value": value,
                    },
                )
                assert outcome.status_code == 200, outcome.text

        analysis = client.get(
            f"/v1/operations/experiments/{experiment_id}/analysis",
            params={"minimum_samples_per_variant": 2},
            headers=auth_headers,
        )
        assert analysis.status_code == 200, analysis.text
        assert analysis.json()["recommended_variant_id"] == "list"

        decision = client.post(
            "/v1/operations/bandit/choose",
            headers=auth_headers,
            json={
                "policy_id": f"title-policy-{suffix}",
                "subject_id": f"subject-{suffix}",
                "arms": ["problem", "list"],
                "context": [1.0, 0.2],
            },
        )
        assert decision.status_code == 200, decision.text
        update = client.post(
            "/v1/operations/bandit/update",
            headers=auth_headers,
            json={
                "policy_id": f"title-policy-{suffix}",
                "arm_id": decision.json()["arm_id"],
                "context": [1.0, 0.2],
                "reward": 1.0,
            },
        )
        assert update.status_code == 200, update.text

        retrospective = client.post(
            f"/v1/operations/accounts/{account_id}/notes/{note_id}/retrospective",
            headers=auth_headers,
        )
        assert retrospective.status_code == 200, retrospective.text
        assert retrospective.json()["next_note_suggestions"]


def test_diagnose_supports_tenant_asset_image_similarity(auth_headers: dict[str, str]) -> None:
    pytest.importorskip("PIL")
    image_module = __import__("PIL.Image", fromlist=["Image"])

    from xhs_skill.api.dependencies import asset_store

    buffer = BytesIO()
    image_module.new("RGB", (16, 16), (255, 0, 0)).save(buffer, format="PNG")
    metadata = asset_store().save_bytes(
        tenant_id="test-tenant",
        filename=f"same-{uuid4().hex}.png",
        content_type="image/png",
        content=buffer.getvalue(),
    )
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/content/diagnose",
            headers=auth_headers,
            json={
                "title": "测试",
                "body": "这是一个原创性检测样本。",
                "references": ["完全不同的文本"],
                "candidate_image_asset_ids": [metadata.asset_id],
                "reference_image_asset_ids": [metadata.asset_id],
            },
        )
    assert response.status_code == 200, response.text
    image_matches = response.json()["originality"]["image_matches"]
    assert image_matches and image_matches[0]["blocked"] is True
    assert image_matches[0]["candidate"] == metadata.asset_id
    assert image_matches[0]["reference"] == metadata.asset_id
    assert "/" not in image_matches[0]["candidate"]
    assert response.json()["originality"]["publication_allowed"] is False
