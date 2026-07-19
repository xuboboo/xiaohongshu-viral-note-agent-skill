from __future__ import annotations

import time

from fastapi.testclient import TestClient

from xhs_skill.api.app import create_app


def test_async_research_job_completes_and_replays_events(auth_headers) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/jobs/research/hot-notes",
            json={"query": "防晒", "time_range": "7d", "limit": 5, "sources": ["fixture"]},
            headers=auth_headers,
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/v1/jobs/{job_id}", headers=auth_headers).json()
            if job["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.01)
        assert job["status"] == "COMPLETED", job
        assert job["result"]["notes"]
