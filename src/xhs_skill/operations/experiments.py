from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.operations.bandit_policy import select_arm
from xhs_skill.operations.models import (
    BanditDecision,
    Experiment,
    ExperimentAssignment,
    ExperimentOutcome,
)
from xhs_skill.operations.repository import OperationsRepository


class ExperimentService:
    def __init__(self, repository: OperationsRepository | None = None) -> None:
        self.repository = repository or OperationsRepository()

    def create(self, experiment: Experiment) -> Experiment:
        if len(experiment.variants) < 2:
            raise ValueError("A/B/n experiment requires at least two variants")
        if not math.isclose(sum(item.allocation for item in experiment.variants), 1.0, rel_tol=1e-6):
            total = sum(item.allocation for item in experiment.variants)
            for item in experiment.variants:
                item.allocation /= total
        experiment.status = "RUNNING"
        experiment.started_at = datetime.now(UTC)
        return self.repository.save_experiment(experiment)

    def assign(self, tenant_id: str, experiment_id: str, subject_id: str) -> ExperimentAssignment:
        experiment = self.repository.get_experiment(tenant_id, experiment_id)
        if experiment is None or experiment.status != "RUNNING":
            raise ValueError("Experiment is not running")
        digest = hashlib.sha256(f"{tenant_id}:{experiment_id}:{subject_id}".encode()).digest()
        point = int.from_bytes(digest[:8], "big") / 2**64
        cumulative = 0.0
        selected = experiment.variants[-1]
        for variant in experiment.variants:
            cumulative += variant.allocation
            if point < cumulative:
                selected = variant
                break
        return self.repository.save_assignment(
            tenant_id,
            ExperimentAssignment(
                experiment_id=experiment_id,
                subject_id=subject_id,
                variant_id=selected.id,
            ),
        )

    def record(self, tenant_id: str, outcome: ExperimentOutcome) -> ExperimentOutcome:
        return self.repository.save_outcome(tenant_id, outcome)

    def summarize(self, tenant_id: str, experiment_id: str) -> dict:
        outcomes = self.repository.experiment_outcomes(tenant_id, experiment_id)
        values: dict[str, list[float]] = {}
        for item in outcomes:
            values.setdefault(item.variant_id, []).append(item.value)
        return {
            variant: {
                "count": len(items),
                "mean": round(sum(items) / len(items), 8),
                "min": min(items),
                "max": max(items),
            }
            for variant, items in values.items()
            if items
        }


def _inverse(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    augmented = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        if abs(divisor) < 1e-12:
            raise ValueError("Bandit covariance matrix is singular")
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
            ]
    return [row[n:] for row in augmented]


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(value * vector[index] for index, value in enumerate(row)) for row in matrix]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class LinUCBPolicy:
    def __init__(
        self,
        repository: OperationsRepository | None = None,
        alpha: float | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository or OperationsRepository()
        self.settings = settings or get_settings()
        self.alpha = (
            float(alpha)
            if alpha is not None
            else float(self.settings.bandit_exploration_alpha)
        )

    def choose(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        subject_id: str,
        arms: list[str],
        context: list[float],
    ) -> BanditDecision:
        if not arms or not context:
            raise ValueError("arms and context are required")
        scored: list[tuple[str, float, float]] = []
        for arm in arms:
            a, b, _ = self.repository.load_bandit_arm(tenant_id, policy_id, arm, len(context))
            inverse = _inverse(a)
            theta = _matvec(inverse, b)
            expected = _dot(theta, context)
            uncertainty = math.sqrt(max(0.0, _dot(context, _matvec(inverse, context))))
            exploration = self.alpha * uncertainty
            scored.append((arm, expected + exploration, exploration))
        arm, score, exploration = select_arm(
            scored,
            strategy=self.settings.bandit_selection_strategy,
            temperature=self.settings.bandit_boltzmann_temperature,
            seed_material=f"{tenant_id}:{policy_id}:{subject_id}",
        )
        return BanditDecision(
            policy_id=policy_id,
            subject_id=subject_id,
            arm_id=arm,
            score=round(score, 8),
            exploration_bonus=round(exploration, 8),
            context=context,
        )

    def update(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        arm_id: str,
        context: list[float],
        reward: float,
    ) -> None:
        a, b, pulls = self.repository.load_bandit_arm(tenant_id, policy_id, arm_id, len(context))
        for i in range(len(context)):
            b[i] += reward * context[i]
            for j in range(len(context)):
                a[i][j] += context[i] * context[j]
        self.repository.save_bandit_arm(tenant_id, policy_id, arm_id, a, b, pulls + 1)
