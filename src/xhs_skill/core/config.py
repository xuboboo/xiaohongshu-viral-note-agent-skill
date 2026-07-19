from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _bundled_path(relative: str) -> Path:
    explicit = os.getenv("XHS_SKILL_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve() / relative
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "SKILL.md").is_file():
            candidate = parent / relative
            if candidate.exists():
                return candidate
    return current.parents[1] / "resources" / relative


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    # 部署配置档：personal（个人轻装）/ team（团队）/ enterprise（企业全功能）
    # personal 模式下隐藏企业噪声，enterprise 默认启用全部治理
    deployment_profile: str = "personal"
    app_host: str = "127.0.0.1"
    app_port: int = 8080
    app_secret_key: str = "development-only-secret-key-change-me"
    auth_required: bool = True
    auth_issuer: str = "xhs-skill"
    auth_audience: str = "xhs-skill-api"
    auth_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    trusted_proxy_cidrs: str = ""
    max_request_body_bytes: int = Field(default=2_097_152, ge=1024, le=104_857_600)
    asset_upload_max_bytes: int = Field(default=52_428_800, ge=1024, le=1_073_741_824)
    authorized_import_max_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    database_url: str = "sqlite+aiosqlite:///./data/xhs_skill.db"
    redis_url: str | None = None
    object_storage_dir: Path = Path("./data/objects")

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_default_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_default_model: str | None = None
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_default_model: str | None = None

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_default_model: str | None = None
    dashscope_api_key: str | None = None
    dashscope_base_url: str | None = None
    qwen_default_model: str | None = None
    ark_api_key: str | None = None
    ark_base_url: str | None = None
    ark_default_model: str | None = None
    zhipu_api_key: str | None = None
    zhipu_base_url: str | None = None
    glm_default_model: str | None = None
    moonshot_api_key: str | None = None
    moonshot_base_url: str | None = None
    kimi_default_model: str | None = None
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    minimax_default_model: str | None = None
    hunyuan_api_key: str | None = None
    hunyuan_base_url: str = "https://api.hunyuan.cloud.tencent.com/v1"
    hunyuan_default_model: str | None = None
    qianfan_api_key: str | None = None
    qianfan_base_url: str | None = None
    qianfan_default_model: str | None = None
    model_providers_file: Path = Field(
        default_factory=lambda: _bundled_path("assets/providers.yaml")
    )
    aws_region: str | None = None

    brave_search_api_key: str | None = None
    brave_search_base_url: str = "https://api.search.brave.com/res/v1"
    searxng_base_url: str | None = None
    bing_search_api_key: str | None = None
    bing_search_base_url: str = "https://api.bing.microsoft.com/v7.0/search"
    google_search_api_key: str | None = None
    google_search_cx: str | None = None
    google_search_base_url: str = "https://www.googleapis.com/customsearch/v1"
    # auto provider resolution when sources/providers omitted:
    # - delegate: ask host agent to websearch + re-call with web_results (MCP-friendly default)
    # - fixture: use deterministic fixture data (local/dev/offline)
    # - error: raise when no live search provider is configured
    search_auto_fallback: str = Field(default="delegate")

    xhs_creator_studio_url: str = "https://creator.xiaohongshu.com"
    xhs_browser_headless: bool = False
    xhs_publish_default_mode: str = "REQUIRE_CONFIRMATION"
    xhs_fully_automated_enabled: bool = False
    xhs_daily_publish_limit: int = 3
    xhs_min_publish_interval_minutes: int = 120
    xhs_session_dir: Path = Path("./playwright/.auth")
    xhs_screenshot_dir: Path = Path("./output/screenshots")
    xhs_selector_config: Path = Field(
        default_factory=lambda: _bundled_path("assets/creator_studio_selectors.yaml")
    )
    xhs_accounts_config: Path = Field(default_factory=lambda: _bundled_path("assets/accounts.yaml"))
    xhs_publish_adapter: str = "creator_studio"
    xhs_manual_export_dir: Path = Path("./output/manual-publish")
    xhs_schedule_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    xhs_scheduling_enabled: bool = True
    xhs_distributed_scheduling_enabled: bool = False
    xhs_require_identity_verified: bool = True

    # High-concurrency runtime
    max_inflight_requests: int = Field(default=512, ge=1, le=100_000)
    sse_max_connections: int = Field(default=10_000, ge=1, le=1_000_000)
    per_tenant_sse_connections: int = Field(default=1_000, ge=1, le=100_000)
    max_queued_waiters: int = Field(default=1024, ge=0, le=100_000)
    concurrency_wait_timeout_seconds: float = Field(default=2.0, gt=0, le=60)
    per_tenant_concurrency: int = Field(default=32, ge=1, le=10_000)
    per_tenant_max_waiters: int = Field(default=128, ge=0, le=100_000)
    per_provider_concurrency: int = Field(default=64, ge=1, le=10_000)
    per_provider_max_waiters: int = Field(default=256, ge=0, le=100_000)
    research_concurrency: int = Field(default=128, ge=1, le=10_000)
    generation_concurrency: int = Field(default=128, ge=1, le=10_000)
    browser_concurrency: int = Field(default=8, ge=1, le=1_000)
    publish_concurrency: int = Field(default=4, ge=1, le=1_000)
    max_tracked_tenants: int = Field(default=10_000, ge=100)
    max_tracked_providers: int = Field(default=1_024, ge=10)
    max_tracked_accounts: int = Field(default=50_000, ge=100)
    distributed_locks_enabled: bool = True
    distributed_lock_ttl_seconds: float = Field(default=120.0, gt=1)
    distributed_lock_wait_timeout_seconds: float = Field(default=5.0, gt=0)
    rate_limit_requests_per_second: float = Field(default=50.0, gt=0)
    rate_limit_burst: int = Field(default=100, ge=1)
    max_rate_limit_keys: int = Field(default=50_000, ge=100)
    provider_rate_limit_requests_per_second: float = Field(default=20.0, gt=0)
    provider_rate_limit_burst: int = Field(default=40, ge=1)
    distributed_rate_limit_enabled: bool = True
    distributed_cache_enabled: bool = True
    cache_max_entries: int = Field(default=10_000, ge=100)
    search_cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    http_max_connections: int = Field(default=1000, ge=10, le=100_000)
    http_max_keepalive_connections: int = Field(default=256, ge=1, le=100_000)
    http_keepalive_expiry_seconds: float = Field(default=30.0, gt=0)
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    http_pool_timeout_seconds: float = Field(default=2.0, gt=0)
    http2_enabled: bool = True

    job_worker_concurrency: int = Field(default=64, ge=1, le=10_000)
    job_queue_capacity: int = Field(default=10_000, ge=1, le=1_000_000)
    job_enqueue_timeout_seconds: float = Field(default=0.25, gt=0, le=30)
    job_max_retries: int = Field(default=3, ge=0, le=20)
    job_dead_letter_capacity: int = Field(default=100_000, ge=100)
    job_worker_fetch_count: int = Field(default=100, ge=1, le=10_000)
    job_worker_block_ms: int = Field(default=5_000, ge=100, le=60_000)
    job_visibility_timeout_ms: int = Field(default=120_000, ge=1_000)
    distributed_jobs_enabled: bool = False
    redis_stream_prefix: str = "xhs"
    redis_consumer_group: str = "xhs-workers"
    redis_event_ttl_seconds: int = Field(default=86_400, ge=60)
    redis_events_enabled: bool = True
    redis_max_connections: int = Field(default=500, ge=10, le=100_000)
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    redis_socket_timeout_seconds: float = Field(default=5.0, gt=0)
    redis_job_ttl_seconds: int = Field(default=604_800, ge=60)

    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_seconds: float = Field(default=30.0, gt=0)
    circuit_breaker_window_seconds: float = Field(default=60.0, gt=0)
    graceful_shutdown_seconds: float = Field(default=30.0, gt=0)
    uvicorn_workers: int = Field(default=1, ge=1, le=256)

    request_timeout_seconds: float = 30.0
    max_search_results: int = Field(default=100, ge=1, le=500)
    sse_retention_events: int = Field(default=5000, ge=100)
    sse_heartbeat_seconds: int = Field(default=15, ge=5)
    mcp_allowed_origins: str = "http://localhost,http://127.0.0.1"

    # Enterprise identity and tenancy
    auth_mode: str = "hybrid"
    oidc_issuer: str = ""
    oidc_audience: str = "xhs-skill-api"
    oidc_discovery_url: str | None = None
    oidc_allowed_algorithms: str = "RS256,ES256,EdDSA"
    oidc_tenant_claim: str = "tenant_id"
    oidc_scope_claim: str = "scope"
    oidc_roles_claim: str = "roles"
    oidc_region_claim: str = "region"
    oidc_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    oidc_http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    oidc_clock_skew_seconds: int = Field(default=60, ge=0, le=300)
    oauth_resource_identifier: str = "http://127.0.0.1:8080"
    # 总闸门；personal/team 在 model_validator 中会默认压成 False，除非显式 env 打开
    enterprise_enabled: bool = False
    enterprise_strict_mode: bool = False
    enterprise_data_dir: Path = Path("./data/enterprise")
    enterprise_default_region: str = "global"
    enterprise_default_daily_budget_usd: float = Field(default=100.0, ge=0)
    enterprise_default_monthly_budget_usd: float = Field(default=2000.0, ge=0)
    enterprise_publish_approval_quorum: int = Field(default=2, ge=1, le=10)
    enterprise_separation_of_duties: bool = True
    enterprise_require_phishing_resistant_mfa: bool = True
    enterprise_policy_enforcement: bool = True
    enterprise_enforce_publish_quorum: bool = False
    enterprise_cost_enforcement: bool = False
    scim_enabled: bool = True
    scim_require_managed_user: bool = False
    scim_reject_inactive_users: bool = True
    scim_base_path: str = "/scim/v2"

    # Enterprise audit, secrets and supply-chain controls
    audit_enabled: bool = True
    audit_dir: Path = Path("./data/audit")
    audit_hmac_key: str | None = None
    audit_s3_bucket: str | None = None
    audit_s3_prefix: str = "xhs-skill-audit"
    audit_s3_object_lock_days: int = Field(default=365, ge=1, le=3650)
    secret_backend: str = "local"
    enterprise_require_external_secret_backend: bool = True
    vault_addr: str | None = None
    vault_token: str | None = None
    vault_transit_mount: str = "transit"
    vault_transit_key: str = "xhs-skill"
    aws_kms_key_id: str | None = None
    plugin_trust_store: Path = Path("./data/enterprise/plugin-trust.json")
    plugin_allow_unsigned_in_development: bool = False
    cost_reservation_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    dlp_enabled: bool = True
    dlp_block_secrets: bool = True
    retention_worker_enabled: bool = False

    # Distributed consistency v5.1
    postgres_state_enabled: bool = False
    enterprise_worker_tenant_ids: list[str] = []
    outbox_worker_enabled: bool = False
    outbox_worker_batch_size: int = Field(default=100, ge=1, le=10_000)
    outbox_max_attempts: int = Field(default=10, ge=1, le=100)
    outbox_lease_seconds: int = Field(default=120, ge=10, le=3600)
    distributed_cancel_poll_seconds: float = Field(default=0.25, gt=0, le=10)
    scheduler_lease_seconds: int = Field(default=180, ge=30, le=3600)
    scheduler_claim_batch_size: int = Field(default=20, ge=1, le=1000)

    # Content intelligence v5.1
    embedding_provider: str = "hashing"
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=512, ge=64, le=4096)
    semantic_similarity_block: float = Field(default=0.92, ge=0, le=1)
    minhash_similarity_block: float = Field(default=0.82, ge=0, le=1)
    simhash_hamming_block: int = Field(default=6, ge=0, le=64)
    rare_phrase_match_block: int = Field(default=2, ge=0, le=100)
    image_phash_distance_block: int = Field(default=6, ge=0, le=64)
    ocr_enabled: bool = False
    learning_ranker_model_path: Path = Path("./data/models/title_lambdamart.txt")
    # 标题混合排序：rule + LTR + semantic → RRF → MMR（可选 CE）
    hybrid_ranker_enabled: bool = True
    hybrid_rrf_k: int = Field(default=60, ge=1, le=200)
    hybrid_mmr_lambda: float = Field(default=0.72, ge=0, le=1)
    # cross-encoder / LLM-as-CE 精排旁路（需模型 key）
    cross_encoder_rerank_enabled: bool = True
    cross_encoder_top_k: int = Field(default=12, ge=2, le=40)
    cross_encoder_rrf_weight: float = Field(default=1.15, ge=0.1, le=3.0)
    cross_encoder_timeout_seconds: float = Field(default=4.0, gt=0, le=30.0)
    cross_encoder_cache_ttl_seconds: float = Field(default=300.0, ge=0, le=3600)
    cross_encoder_max_provider_attempts: int = Field(default=1, ge=1, le=5)

    # 可选封面图 Provider：auto|noop|openai|dashscope（有 key 时 auto 自动启用）
    image_provider: str = "auto"
    image_api_key: str | None = None
    image_base_url: str | None = None
    image_model: str | None = None
    image_output_dir: Path = Path("./data/generated-images")
    # 选择器 canary
    selector_canary_enabled: bool = True
    selector_canary_alert_webhook: str | None = None
    selector_pin_version: str | None = None

    # Operations loop v5.1
    operations_db_path: Path = Path("./data/operations.sqlite3")
    default_content_calendar_days: int = Field(default=30, ge=7, le=365)
    bandit_exploration_alpha: float = Field(default=1.0, gt=0, le=10)
    # greedy_ucb | boltzmann — boltzmann 在 UCB 分数上做温度探索
    bandit_selection_strategy: str = "greedy_ucb"
    bandit_boltzmann_temperature: float = Field(default=0.35, gt=0, le=5)
    asset_library_dir: Path = Path("./data/asset-library")
    post_publish_sync_enabled: bool = True
    post_publish_sync_delays_minutes: list[int] = [60, 1440, 4320]
    post_publish_sync_max_attempts: int = Field(default=8, ge=1, le=100)
    post_publish_sync_lease_seconds: int = Field(default=180, ge=30, le=3600)

    @field_validator("app_secret_key")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) < 32:
            raise ValueError("APP_SECRET_KEY must contain at least 32 bytes")
        return value

    @field_validator("search_auto_fallback")
    @classmethod
    def validate_search_auto_fallback(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"delegate", "fixture", "error"}
        if normalized not in allowed:
            raise ValueError(f"SEARCH_AUTO_FALLBACK must be one of {sorted(allowed)}")
        return normalized

    @model_validator(mode="after")
    def validate_production_security(self) -> Settings:
        profile = self.deployment_profile.strip().lower()
        if profile not in {"personal", "team", "enterprise"}:
            raise ValueError("DEPLOYMENT_PROFILE must be personal, team or enterprise")
        # enterprise 配置档默认打开企业闸门；personal/team 保持默认关闭（可用 env 显式打开）
        if profile == "enterprise" and not self.enterprise_enabled:
            self.enterprise_enabled = True
        if profile == "personal" and self.scim_enabled and not self.enterprise_enabled:
            # 个人轻装：避免 scim 等企业噪声默认开着
            self.scim_enabled = False
        env = self.app_env.strip().lower()
        insecure_values = {
            "development-only-secret-key-change-me",
            "replace-with-at-least-32-random-bytes",
            "change-me-change-me-change-me-change-me",
            "your-secret-key-here-change-me-now",
        }
        normalized_secret = self.app_secret_key.strip().lower()
        weak_pattern = (
            normalized_secret in insecure_values
            or len(set(self.app_secret_key)) < 10
            or len(re.findall(r"[a-z]", self.app_secret_key)) == 0
            or len(re.findall(r"[A-Z]", self.app_secret_key)) == 0
            or len(re.findall(r"[0-9]", self.app_secret_key)) == 0
            or len(re.findall(r"[^A-Za-z0-9]", self.app_secret_key)) == 0
        )
        if env not in {"development", "test"} and weak_pattern:
            raise ValueError(
                "APP_SECRET_KEY must be a non-placeholder high-entropy secret outside development/test"
            )
        if env not in {"development", "test"} and not self.auth_required:
            raise ValueError("AUTH_REQUIRED cannot be disabled outside development/test")
        if self.xhs_distributed_scheduling_enabled and not self.postgres_state_enabled:
            raise ValueError(
                "XHS_DISTRIBUTED_SCHEDULING_ENABLED requires POSTGRES_STATE_ENABLED=true"
            )
        if self.postgres_state_enabled and not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("POSTGRES_STATE_ENABLED requires a PostgreSQL DATABASE_URL")
        if (
            env not in {"development", "test"}
            and self.xhs_publish_adapter == "creator_studio"
            and self.uvicorn_workers > 1
        ):
            raise ValueError("Creator Studio browser publishing requires one API process unless a shared enterprise state backend is configured")
        if (
            env not in {"development", "test"}
            and self.uvicorn_workers > 1
            and not self.redis_url
            and any(
                (
                    self.distributed_jobs_enabled,
                    self.redis_events_enabled,
                    self.distributed_rate_limit_enabled,
                    self.distributed_locks_enabled,
                )
            )
        ):
            raise ValueError("Multi-process production mode requires REDIS_URL")
        mode = self.auth_mode.strip().lower()
        if mode not in {"local", "oidc", "hybrid"}:
            raise ValueError("AUTH_MODE must be local, oidc or hybrid")
        if (
            mode in {"oidc", "hybrid"}
            and env not in {"development", "test"}
            and self.enterprise_strict_mode
        ):
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required in enterprise production")
            if not self.oauth_resource_identifier.startswith("https://"):
                raise ValueError("OAUTH_RESOURCE_IDENTIFIER must use HTTPS in production")
        if (
            self.enterprise_enabled
            and self.enterprise_strict_mode
            and env not in {"development", "test"}
            and not self.enterprise_enforce_publish_quorum
        ):
            raise ValueError("ENTERPRISE_ENFORCE_PUBLISH_QUORUM must be enabled in enterprise production")
        if (
            self.enterprise_enabled
            and self.enterprise_strict_mode
            and env not in {"development", "test"}
            and not self.enterprise_cost_enforcement
        ):
            raise ValueError("ENTERPRISE_COST_ENFORCEMENT must be enabled in enterprise production")
        if (
            self.audit_enabled
            and self.enterprise_strict_mode
            and env not in {"development", "test"}
            and not self.audit_hmac_key
        ):
            raise ValueError("AUDIT_HMAC_KEY is required when audit is enabled in production")
        if self.secret_backend not in {"local", "vault", "aws_kms"}:
            raise ValueError("SECRET_BACKEND must be local, vault or aws_kms")
        if (
            self.enterprise_enabled
            and self.enterprise_strict_mode
            and self.enterprise_require_external_secret_backend
            and env not in {"development", "test"}
            and self.secret_backend == "local"
        ):
            raise ValueError("Enterprise strict mode requires Vault Transit or AWS KMS")
        if self.secret_backend == "vault" and (not self.vault_addr or not self.vault_token):
            raise ValueError("VAULT_ADDR and VAULT_TOKEN are required for Vault secrets")
        if self.secret_backend == "aws_kms" and not self.aws_kms_key_id:
            raise ValueError("AWS_KMS_KEY_ID is required for AWS KMS secrets")
        return self

    @property
    def profile(self) -> str:
        """当前部署配置档：personal / team / enterprise。"""
        return self.deployment_profile.strip().lower()

    @property
    def profile_features(self) -> dict[str, bool]:
        """根据 profile 返回功能开关。"""
        p = self.profile
        return {
            # Content plane: always on
            "research": True,
            "generation": True,
            "rewrite": True,
            "verifiers": True,
            # Publish plane: always on
            "publishing": True,
            "scheduling": self.xhs_scheduling_enabled,
            # Ops plane: always on
            "operations": True,
            "post_publish_sync": self.post_publish_sync_enabled,
            # Enterprise plane: profile-dependent
            "enterprise_quota": p == "enterprise",
            "enterprise_approvals": p == "enterprise",
            "enterprise_audit": p in ("team", "enterprise"),
            "enterprise_oidc": p in ("team", "enterprise"),
            "enterprise_scim": p == "enterprise",
            "enterprise_cost_enforcement": p == "enterprise" and self.enterprise_cost_enforcement,
            "enterprise_outbox": p == "enterprise" and self.postgres_state_enabled,
            # UI noise control
            "show_enterprise_cli": p == "enterprise",
        }

    def is_enterprise_plane_enabled(self) -> bool:
        """企业平面是否启用。"""
        return self.profile == "enterprise" and self.enterprise_enabled

    def ensure_directories(self) -> None:
        for directory in (
            self.object_storage_dir,
            self.xhs_session_dir,
            self.xhs_screenshot_dir,
            self.xhs_manual_export_dir,
            self.enterprise_data_dir,
            self.audit_dir,
            self.asset_library_dir,
            self.operations_db_path.parent,
            self.learning_ranker_model_path.parent,
            self.image_output_dir,
            Path("./data"),
            Path("./output"),
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                directory.chmod(0o700)
            except OSError:
                pass


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
