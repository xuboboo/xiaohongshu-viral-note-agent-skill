"""一键 Doctor：配置 / 算法 / 模型 / 安装路径就绪诊断。

不触网、不登录创作者中心；输出可给 CLI 与 /health 风格消费。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from xhs_skill import __version__
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.profile import active_planes, current_profile
from xhs_skill.operations.bandit_context import BANDIT_CONTEXT_DIM, BANDIT_CONTEXT_NAMES
from xhs_skill.providers.openai_images import get_image_provider
from xhs_skill.providers.registry import ProviderRegistry
from xhs_skill.publishing.selector_health import selector_bundle_fingerprint
from xhs_skill.ranking.features import FEATURE_ORDER
from xhs_skill.ranking.learning_ranker import LambdaMARTRanker


def _check(
    name: str,
    ok: bool,
    *,
    level: str = "info",
    detail: str = "",
    hint: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "level": level if not ok else "ok",
        "detail": detail,
        "hint": hint,
    }


def run_doctor(settings: Settings | None = None) -> dict[str, Any]:
    """汇总环境与算法能力快照。"""
    settings = settings or get_settings()
    checks: list[dict[str, Any]] = []

    # 安装路径
    try:
        import xhs_skill as pkg

        import_path = Path(pkg.__file__).resolve()
        parts = set(import_path.parts)
        from_build = "build" in parts and "lib" in parts
        checks.append(
            _check(
                "import_path",
                not from_build,
                level="error",
                detail=str(import_path),
                hint="pip install -e . && python scripts/clean_stale_build.py",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check(
                "import_path",
                False,
                level="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    # 配置档
    profile = current_profile()
    planes = active_planes()
    checks.append(
        _check(
            "deployment_profile",
            profile in {"personal", "team", "enterprise"},
            detail=f"{profile}; planes={','.join(planes)}",
        )
    )

    # 模型 Provider
    registry = ProviderRegistry(settings)
    providers = registry.list()
    checks.append(
        _check(
            "model_providers",
            bool(providers),
            level="warn",
            detail=",".join(providers) if providers else "none configured",
            hint="设置 OPENAI_API_KEY / ANTHROPIC_API_KEY 等",
        )
    )

    # 图片 Provider
    image = get_image_provider(settings)
    image_ok = getattr(image, "name", "") != "noop"
    checks.append(
        _check(
            "image_provider",
            True,  # noop 也合法
            detail=f"mode={settings.image_provider}; active={getattr(image, 'name', type(image).__name__)}; ready={image_ok}",
            hint="IMAGE_PROVIDER=auto 并配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY",
        )
    )

    # Embedding
    emb = settings.embedding_provider.strip().lower()
    emb_ready = emb == "hashing" or bool(
        settings.embedding_api_key or settings.openai_api_key
    )
    checks.append(
        _check(
            "embedding_provider",
            emb_ready,
            level="warn",
            detail=f"{emb}; ready={emb_ready}",
            hint="远程 embedding 需要 EMBEDDING_API_KEY 或 OPENAI_API_KEY",
        )
    )

    # LambdaMART 模型
    model_path = Path(settings.learning_ranker_model_path)
    ranker = LambdaMARTRanker(model_path if model_path.exists() else None)
    if model_path.exists():
        verify = ranker.verify_artifact(model_path)
        checks.append(
            _check(
                "lambdamart_model",
                bool(verify.get("ok")),
                level="warn",
                detail=json_safe(verify),
                hint="python scripts/export_ltr_from_metrics.py ... --train-output",
            )
        )
    else:
        checks.append(
            _check(
                "lambdamart_model",
                True,
                detail="missing (rule fallback active)",
                hint=f"可选训练产物: {model_path}",
            )
        )

    # Hybrid / CE 配置
    checks.append(
        _check(
            "hybrid_ranker",
            settings.hybrid_ranker_enabled,
            detail=(
                f"enabled={settings.hybrid_ranker_enabled}; "
                f"rrf_k={settings.hybrid_rrf_k}; mmr_lambda={settings.hybrid_mmr_lambda}"
            ),
        )
    )
    ce_enabled = settings.cross_encoder_rerank_enabled
    ce_ready = ce_enabled and bool(providers)
    checks.append(
        _check(
            "cross_encoder",
            True if not ce_enabled else ce_ready,
            level="warn",
            detail=(
                f"enabled={ce_enabled}; providers={len(providers)}; "
                f"timeout={settings.cross_encoder_timeout_seconds}s; "
                f"cache_ttl={settings.cross_encoder_cache_ttl_seconds}s; "
                f"max_attempts={settings.cross_encoder_max_provider_attempts}"
            ),
            hint="CE 需至少一个 chat provider；无 key 时会静默跳过",
        )
    )

    # Bandit
    checks.append(
        _check(
            "bandit",
            settings.bandit_exploration_alpha > 0,
            detail=(
                f"strategy={settings.bandit_selection_strategy}; "
                f"alpha={settings.bandit_exploration_alpha}; "
                f"context_dim={BANDIT_CONTEXT_DIM}; "
                f"fields={','.join(BANDIT_CONTEXT_NAMES[:4])}..."
            ),
        )
    )

    # LTR 特征 schema
    checks.append(
        _check(
            "ltr_feature_schema",
            len(FEATURE_ORDER) == 10,
            detail=f"dim={len(FEATURE_ORDER)}; order={FEATURE_ORDER}",
        )
    )

    # 选择器资产
    pin = selector_bundle_fingerprint(settings.xhs_selector_config)
    pin_ok = bool(pin.get("sha256"))
    expected = (settings.selector_pin_version or "").strip().lower()
    if expected and pin.get("sha256"):
        pin_ok = pin["sha256"].lower() == expected
    checks.append(
        _check(
            "selector_bundle",
            pin_ok if expected else bool(pin.get("sha256")),
            level="warn",
            detail=(
                f"path={pin.get('path')}; sha256={pin.get('sha256', '')[:16]}...; "
                f"pin={expected or 'unpinned'}"
            ),
            hint="设置 SELECTOR_PIN_VERSION 钉扎当前 yaml",
        )
    )

    # 发布/同步
    checks.append(
        _check(
            "post_publish_sync",
            settings.post_publish_sync_enabled,
            detail=f"enabled={settings.post_publish_sync_enabled}; delays={settings.post_publish_sync_delays_minutes}",
        )
    )

    # 发布门禁（本地、不触网）：毒包 BLOCKED / 干净包 HUMAN_REVIEW_REQUIRED
    try:
        from xhs_skill.publishing.publication_gate import reverify_package
        from xhs_skill.schemas.content import DeliveryPackage

        toxic = DeliveryPackage(
            task_id="doctor",
            trace_id="doctor",
            selected_title="神药",
            body="本产品可以治疗失眠，100%有效，永久有效。",
            content_hash="doctor-toxic",
            compliance_report={"passed": True},
            originality_report={"publication_allowed": True},
            publication_status="ALLOWED",
        )
        clean = DeliveryPackage(
            task_id="doctor",
            trace_id="doctor",
            selected_title="通勤包怎么选更省心",
            body="先看容量和背负舒适度，再对照自己的使用场景，不适合的人群也可以直接跳过。",
            content_hash="doctor-clean",
            compliance_report={"passed": True},
            originality_report={"publication_allowed": True},
            publication_status="ALLOWED",
        )
        toxic_out = reverify_package(toxic, settings=settings)
        clean_out = reverify_package(clean, settings=settings)
        gate_ok = (
            toxic_out.publication_status == "BLOCKED"
            and clean_out.publication_status == "HUMAN_REVIEW_REQUIRED"
            and bool((clean_out.quality_report or {}).get("server_reverified"))
        )
        checks.append(
            _check(
                "publication_gate",
                gate_ok,
                level="error",
                detail=(
                    f"toxic={toxic_out.publication_status}; "
                    f"clean={clean_out.publication_status}; "
                    f"server_reverified={bool((clean_out.quality_report or {}).get('server_reverified'))}"
                ),
                hint="检查 publishing.publication_gate.reverify_package / claims / compliance",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check(
                "publication_gate",
                False,
                level="error",
                detail=f"{type(exc).__name__}: {exc}",
                hint="pip install -e . 后重试 doctor",
            )
        )

    errors = sum(1 for item in checks if not item["ok"] and item["level"] == "error")
    warns = sum(1 for item in checks if not item["ok"] and item["level"] == "warn")
    ready = errors == 0

    return {
        "version": __version__,
        "profile": profile,
        "planes": planes,
        "ready": ready,
        "summary": {
            "checks": len(checks),
            "errors": errors,
            "warnings": warns,
            "passed": sum(1 for item in checks if item["ok"]),
        },
        "checks": checks,
        "golden_path": [
            "1. xhs-skill doctor  # 本命令",
            "2. 研究: search_hot_notes / generate_from_hot(dry_run=true)  # 先看 ux.next_step",
            "3. 成稿: generate_xhs_note 或 generate_from_hot(dry_run=false)  # 看 creation_bundle + readiness",
            "4. 门禁: quality_report.readiness / ux.status（blocked 勿发布）",
            "5. 发布: draft → preview → approve → execute（需用户确认）",
            "6. 回流: scripts/export_ltr_from_metrics.py；publish canary 检查选择器",
        ],
        "config_knobs": {
            "hybrid_ranker_enabled": settings.hybrid_ranker_enabled,
            "cross_encoder_rerank_enabled": settings.cross_encoder_rerank_enabled,
            "cross_encoder_timeout_seconds": settings.cross_encoder_timeout_seconds,
            "image_provider": settings.image_provider,
            "embedding_provider": settings.embedding_provider,
            "bandit_selection_strategy": settings.bandit_selection_strategy,
            "deployment_profile": settings.deployment_profile,
        },
    }


def json_safe(value: object) -> str:
    if isinstance(value, dict):
        parts = [f"{k}={v}" for k, v in value.items()]
        return "; ".join(parts)
    return str(value)