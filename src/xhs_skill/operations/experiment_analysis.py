from __future__ import annotations

import math
import statistics
from collections import defaultdict

from pydantic import BaseModel, Field

from xhs_skill.operations.models import Experiment, ExperimentOutcome


class VariantAnalysis(BaseModel):
    variant_id: str
    sample_size: int
    mean: float
    standard_error: float
    confidence_low: float
    confidence_high: float
    lift_vs_control: float | None = None
    probability_best: float | None = Field(default=None, ge=0, le=1)


class ExperimentAnalysis(BaseModel):
    experiment_id: str
    primary_metric: str
    control_variant_id: str
    variants: list[VariantAnalysis]
    recommended_variant_id: str | None = None
    decision: str
    caveat: str = (
        "置信区间使用正态近似；样本不足、分配偏差或多重检验会降低结论可靠性。"
    )


def analyze_experiment(
    experiment: Experiment,
    outcomes: list[ExperimentOutcome],
    *,
    minimum_samples_per_variant: int = 20,
) -> ExperimentAnalysis:
    if not experiment.variants:
        raise ValueError("Experiment requires at least one variant")
    control = experiment.variants[0].id
    grouped: dict[str, list[float]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.metric == experiment.primary_metric:
            grouped[outcome.variant_id].append(float(outcome.value))
    analyses: list[VariantAnalysis] = []
    control_values = grouped.get(control, [])
    control_mean = statistics.fmean(control_values) if control_values else 0.0
    for variant in experiment.variants:
        values = grouped.get(variant.id, [])
        n = len(values)
        mean = statistics.fmean(values) if values else 0.0
        stdev = statistics.stdev(values) if n >= 2 else 0.0
        error = stdev / math.sqrt(n) if n else 0.0
        analyses.append(
            VariantAnalysis(
                variant_id=variant.id,
                sample_size=n,
                mean=round(mean, 8),
                standard_error=round(error, 8),
                confidence_low=round(mean - 1.96 * error, 8),
                confidence_high=round(mean + 1.96 * error, 8),
                lift_vs_control=(
                    round((mean - control_mean) / abs(control_mean), 8)
                    if variant.id != control and control_mean != 0
                    else (0.0 if variant.id == control else None)
                ),
            )
        )
    eligible = [item for item in analyses if item.sample_size >= minimum_samples_per_variant]
    winner = max(eligible, key=lambda item: item.mean, default=None)
    if len(eligible) < len(experiment.variants):
        decision = "CONTINUE_COLLECTING"
        recommended = None
    elif winner is None:
        decision = "NO_DATA"
        recommended = None
    else:
        control_analysis = next(item for item in analyses if item.variant_id == control)
        intervals_overlap = not (
            winner.confidence_low > control_analysis.confidence_high
            or winner.confidence_high < control_analysis.confidence_low
        )
        decision = "INCONCLUSIVE" if intervals_overlap else "SELECT_WINNER"
        recommended = winner.variant_id if decision == "SELECT_WINNER" else None
    return ExperimentAnalysis(
        experiment_id=experiment.id,
        primary_metric=experiment.primary_metric,
        control_variant_id=control,
        variants=analyses,
        recommended_variant_id=recommended,
        decision=decision,
    )
