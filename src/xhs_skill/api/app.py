from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from xhs_skill import __version__
from xhs_skill.a2a.server import router as a2a_router
from xhs_skill.api.dependencies import (
    account_service,
    job_service,
    login_flow,
    operations_service,
    publishing_service,
)
from xhs_skill.api.middleware import HighConcurrencyMiddleware
from xhs_skill.api.routes import (
    accounts,
    assets,
    authentication,
    content,
    jobs,
    operations,
    providers,
    publishing,
    research,
)
from xhs_skill.api.security import require_scopes
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import get_settings
from xhs_skill.core.distributed_lock import get_distributed_lock_manager
from xhs_skill.core.errors import XHSSkillError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.core.logging import configure_logging
from xhs_skill.core.metrics import ACTIVE_JOBS, JOB_QUEUE, render_metrics
from xhs_skill.enterprise.metadata import router as enterprise_metadata_router
from xhs_skill.enterprise.middleware import EnterpriseAuditMiddleware
from xhs_skill.enterprise.routes import router as enterprise_router
from xhs_skill.enterprise.scim import router as scim_router
from xhs_skill.mcp.http import router as mcp_router
from xhs_skill.storage.redis_runtime import get_redis_runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    yield
    service = job_service()
    await service.shutdown()
    await service.broker.close()
    await service.repository.close()
    await login_flow().shutdown()
    await account_service().close()
    await operations_service().close()
    await publishing_service().shutdown()
    await get_http_pool().close()
    await get_distributed_lock_manager().close()
    await get_redis_runtime().close()


def create_app() -> FastAPI:
    configure_logging()
    get_settings().ensure_directories()
    app = FastAPI(
        title="小红书爆款笔记生成 agent Skill",
        version=__version__,
        description="Enterprise-grade hot-note research, multi-model generation, account analytics and controlled publishing Agent Skill.",
        lifespan=lifespan,
    )
    app.add_middleware(EnterpriseAuditMiddleware)
    app.add_middleware(HighConcurrencyMiddleware)
    routers = [
        research.router,
        content.router,
        accounts.router,
        assets.router,
        authentication.router,
        publishing.router,
        jobs.router,
        operations.router,
        providers.router,
        mcp_router,
        a2a_router,
    ]
    # personal/team 隐藏 enterprise 路由噪声；enterprise profile 再挂载
    settings = get_settings()
    if settings.profile in ("team", "enterprise"):
        routers.append(enterprise_metadata_router)
    if settings.profile == "enterprise":
        routers.extend((enterprise_router, scim_router))
    for router in routers:
        app.include_router(router)

    @app.exception_handler(XHSSkillError)
    async def skill_error_handler(_: Request, exc: XHSSkillError):
        headers = {}
        if "retry_after_seconds" in exc.details:
            headers["Retry-After"] = str(max(1, int(float(exc.details["retry_after_seconds"]))))
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.get("/health/live")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/health", dependencies=[Depends(require_scopes("admin:read"))])
    async def authenticated_health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready")
    async def ready() -> dict:
        service = job_service()
        settings = get_settings()
        redis_ready = None
        postgres_ready = None
        if settings.redis_url and any(
            (
                settings.redis_events_enabled,
                settings.distributed_jobs_enabled,
                settings.distributed_rate_limit_enabled,
                settings.distributed_locks_enabled,
            )
        ):
            try:
                redis_ready = await get_redis_runtime().ping()
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail=f"Redis is not ready: {type(exc).__name__}"
                ) from exc
        if settings.postgres_state_enabled:
            try:
                postgres = operations_service().postgres
                if postgres is None:
                    raise RuntimeError("PostgreSQL state store is not configured")
                postgres_ready = await postgres.ping()
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail=f"PostgreSQL is not ready: {type(exc).__name__}"
                ) from exc
        await service.async_stats()
        return {
            "status": "ready",
            "version": __version__,
            "redis": redis_ready,
            "postgres": postgres_ready,
        }

    @app.get(
        "/health/diagnostics",
        dependencies=[Depends(require_scopes("admin:read"))],
    )
    async def health_diagnostics() -> dict:
        service = job_service()
        settings = get_settings()
        return {
            "status": "ok",
            "version": __version__,
            "concurrency": get_concurrency_controller().snapshot(),
            "jobs": await service.async_stats(),
            "event_backend": type(service.broker.backend).__name__,
            "job_repository": type(service.repository.backend).__name__,
            "redis_configured": bool(settings.redis_url),
            "postgres_configured": settings.postgres_state_enabled,
        }

    @app.get(
        "/health/doctor",
        dependencies=[Depends(require_scopes("admin:read"))],
    )
    async def health_doctor() -> dict:
        """一键诊断：配置档、算法能力、模型签名、选择器钉扎。"""
        from xhs_skill.core.doctor import run_doctor

        return run_doctor()

    @app.get(
        "/metrics",
        include_in_schema=False,
        dependencies=[Depends(require_scopes("admin:read"))],
    )
    async def metrics() -> Response:
        stats = await job_service().async_stats()
        JOB_QUEUE.set(stats["queue_depth"])
        ACTIVE_JOBS.set(stats["active_jobs"])
        payload, media_type = render_metrics()
        return Response(content=payload, media_type=media_type)

    return app
