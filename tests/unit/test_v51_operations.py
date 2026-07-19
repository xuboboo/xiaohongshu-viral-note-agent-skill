from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from xhs_skill.core.config import Settings
from xhs_skill.operations.assets import AssetLibrary
from xhs_skill.operations.experiment_analysis import analyze_experiment
from xhs_skill.operations.experiments import ExperimentService, LinUCBPolicy
from xhs_skill.operations.models import (
    Experiment,
    ExperimentOutcome,
    ExperimentVariant,
    PostPublishSyncTask,
    PublishedMetrics,
)
from xhs_skill.operations.repository import OperationsRepository
from xhs_skill.operations.service import OperationsService
from xhs_skill.storage.assets import AssetStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        operations_db_path=tmp_path / "operations.sqlite3",
        asset_library_dir=tmp_path / "library",
        object_storage_dir=tmp_path / "objects",
        data_dir=tmp_path / "data",
    )


def test_operations_loop_experiment_bandit_and_retrospective(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = OperationsRepository(settings)
    service = OperationsService(repository)
    experiment = Experiment(
        tenant_id="tenant-a",
        account_id="account-a",
        name="标题测试",
        hypothesis="清单标题提升收藏",
        primary_metric="save_rate",
        variants=[
            ExperimentVariant(id="control", name="问题型", payload={}),
            ExperimentVariant(id="list", name="清单型", payload={}),
        ],
    )
    ExperimentService(repository).create(experiment)
    for index in range(25):
        for variant, value in (("control", 0.02), ("list", 0.05)):
            repository.save_outcome(
                "tenant-a",
                ExperimentOutcome(
                    experiment_id=experiment.id,
                    subject_id=f"{variant}-{index}",
                    variant_id=variant,
                    metric="save_rate",
                    value=value,
                ),
            )
    analysis = analyze_experiment(experiment, repository.experiment_outcomes("tenant-a", experiment.id))
    assert analysis.recommended_variant_id == "list"

    bandit = LinUCBPolicy(repository, alpha=0.5)
    decision = bandit.choose(
        tenant_id="tenant-a",
        policy_id="title-policy",
        subject_id="subject-1",
        arms=["problem", "list"],
        context=[1.0, 0.2],
    )
    bandit.update(
        tenant_id="tenant-a",
        policy_id="title-policy",
        arm_id=decision.arm_id,
        context=[1.0, 0.2],
        reward=1.0,
    )

    repository.save_metrics(
        PublishedMetrics(
            tenant_id="tenant-a",
            account_id="account-a",
            note_id="note-1",
            views=1000,
            likes=50,
            saves=10,
            comments=5,
            shares=3,
            search_views=50,
            content_features={"topic": "防晒", "title_number": 1.0},
        )
    )
    retrospective = service.retrospective("tenant-a", "account-a", "note-1")
    assert retrospective.next_note_suggestions


def test_asset_library_only_imports_existing_tenant_asset(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = AssetStore(settings)
    metadata = store.save_bytes(
        tenant_id="tenant-a",
        filename="sample.json",
        content_type="application/json",
        content=b'{"ok":true}',
    )
    library = AssetLibrary(settings, OperationsRepository(settings))
    record = library.import_asset_id(
        metadata.asset_id,
        asset_store=store,
        tenant_id="tenant-a",
        tags=["source"],
    )
    assert record.metadata["source_asset_id"] == metadata.asset_id


def test_post_publish_sync_task_lease_and_retry(tmp_path: Path) -> None:
    repository = OperationsRepository(_settings(tmp_path))
    task = PostPublishSyncTask(
        tenant_id="tenant-a",
        account_id="account-a",
        note_id="note-a",
        due_at=datetime.now(UTC) - timedelta(seconds=1),
        max_attempts=2,
    )
    repository.enqueue_post_publish_sync(task)
    claimed = repository.claim_post_publish_sync(
        tenant_id="tenant-a",
        worker_id="worker-a",
        now=datetime.now(UTC),
        lease_seconds=30,
    )
    assert len(claimed) == 1
    retried = repository.finish_post_publish_sync(
        claimed[0],
        success=False,
        error="temporary",
        retry_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert retried.status == "RETRY"
    claimed_again = repository.claim_post_publish_sync(
        tenant_id="tenant-a",
        worker_id="worker-b",
        now=datetime.now(UTC),
        lease_seconds=30,
    )
    assert len(claimed_again) == 1
    finished = repository.finish_post_publish_sync(claimed_again[0], success=True)
    assert finished.status == "COMPLETED"
