from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path

import typer
import uvicorn

from xhs_skill.accounts import AccountService
from xhs_skill.browser import LoginFlow
from xhs_skill.core.auth import issue_token
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.audit import AuditLedger
from xhs_skill.enterprise.quota import CostLedger
from xhs_skill.enterprise.repository import EnterpriseRepository
from xhs_skill.jobs import JobService
from xhs_skill.orchestrator import ContentWorkflow
from xhs_skill.publishing import PublishingService
from xhs_skill.research import ResearchService
from xhs_skill.schemas.account import AccountAnalytics
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.publishing import PublishMode
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.search.adaptive import ClientWebSearchRequired
from xhs_skill.storage.assets import AssetStore
from xhs_skill.ux.envelope import enrich_tool_result

app = typer.Typer(help="小红书爆款笔记生成 agent Skill")
account_app = typer.Typer(help="账号分析与授权登录")
publish_app = typer.Typer(help="受控发布")
provider_app = typer.Typer(help="模型 Provider")
auth_app = typer.Typer(help="API 身份认证")
asset_app = typer.Typer(help="租户隔离素材")
enterprise_app = typer.Typer(help="企业租户、预算与审计")
app.add_typer(account_app, name="account")
app.add_typer(publish_app, name="publish")
app.add_typer(provider_app, name="provider")
app.add_typer(auth_app, name="auth")
app.add_typer(asset_app, name="asset")
# enterprise 命令组仅在 enterprise profile 下显示
if get_settings().profile == "enterprise":
    app.add_typer(enterprise_app, name="enterprise")


def _write(data: object, output: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        typer.echo(f"Saved: {output}")
    else:
        typer.echo(text)


def _emit(tool: str, data: object, output: Path | None = None) -> None:
    """CLI 与 MCP 共用体验信封。"""
    payload = data if isinstance(data, dict) else {"result": data}
    _write(enrich_tool_result(tool, payload), output)


def _emit_needs_web(exc: ClientWebSearchRequired, output: Path | None = None) -> None:
    _write(enrich_tool_result("search_hot_notes", exc.to_payload()), output)


@app.command("profile")
def show_profile() -> None:
    """显示当前部署配置档和活跃功能。"""
    from xhs_skill.core.profile import active_planes, current_profile

    settings = get_settings()
    profile = current_profile()
    planes = active_planes()
    features = settings.profile_features

    typer.echo(f"Profile: {profile}")
    typer.echo(f"Active planes: {', '.join(planes)}")
    typer.echo("Features:")
    for name, enabled in sorted(features.items()):
        status = "on" if enabled else "off"
        typer.echo(f"  {name}: {status}")


@app.command("doctor")
def doctor_cmd(
    output: Path | None = typer.Option(None, "--output", "-o", help="写入 JSON 报告"),
    strict: bool = typer.Option(False, "--strict", help="有 warning 也以退出码 1 失败"),
) -> None:
    """一键诊断：配置档、模型/图片 Provider、LTR 模型签名、CE 超时缓存、选择器钉扎。"""
    from xhs_skill.core.doctor import run_doctor

    report = run_doctor()
    # doctor 自带 golden_path；再挂通用 ux 方便脚本消费
    payload = dict(report)
    payload.setdefault(
        "next_step",
        (report.get("golden_path") or ["xhs-skill generate --topic ..."])[0]
        if isinstance(report.get("golden_path"), list)
        else "xhs-skill generate --topic ...",
    )
    _emit("doctor", payload, output)
    if not report.get("ready"):
        raise typer.Exit(code=2)
    if strict and report.get("summary", {}).get("warnings", 0) > 0:
        raise typer.Exit(code=1)


@auth_app.command("token")
def create_token(
    subject: str = typer.Option(..., "--subject"),
    tenant_id: str = typer.Option(..., "--tenant"),
    scope: list[str] = typer.Option(..., "--scope"),
    auth_level: int = typer.Option(1, "--auth-level", min=1, max=3),
    role: list[str] = typer.Option([], "--role"),
    amr: list[str] = typer.Option([], "--amr"),
    region: str | None = typer.Option(None, "--region"),
    ttl_seconds: int = typer.Option(3600, "--ttl-seconds", min=60, max=86400),
) -> None:
    """Create a short-lived locally signed service token."""
    typer.echo(
        issue_token(
            subject=subject,
            tenant_id=tenant_id,
            scopes=set(scope),
            auth_level=auth_level,
            roles=set(role),
            amr=set(amr),
            region=region,
            ttl_seconds=ttl_seconds,
        )
    )


@enterprise_app.command("tenant")
def enterprise_tenant(tenant_id: str = typer.Option(..., "--tenant")) -> None:
    """Show the effective tenant policy from the local enterprise repository."""
    _emit(
        "get_enterprise_controls",
        {"tenant": EnterpriseRepository().get_tenant(tenant_id).model_dump(mode="json")},
        None,
    )


@enterprise_app.command("budget")
def enterprise_budget(tenant_id: str = typer.Option(..., "--tenant")) -> None:
    """Show daily and monthly cost commitments and remaining budget."""
    _emit("get_enterprise_budget", CostLedger().summary(tenant_id).model_dump(mode="json"), None)


@enterprise_app.command("audit-verify")
def enterprise_audit_verify(tenant_id: str = typer.Option(..., "--tenant")) -> None:
    """Verify the tenant append-only audit hash chain."""
    report = AuditLedger().verify(tenant_id)
    _emit("verify_enterprise_audit", report.model_dump(mode="json"), None)
    if not report.valid:
        raise typer.Exit(code=2)


@asset_app.command("import")
def import_asset(
    input_: Path = typer.Option(..., "--input"),
    tenant_id: str = typer.Option("local", "--tenant"),
    content_type: str | None = typer.Option(None, "--content-type"),
) -> None:
    item = AssetStore().save_bytes(
        tenant_id=tenant_id,
        filename=input_.name,
        content_type=content_type,
        content=input_.read_bytes(),
    )
    _write(
        {
            "asset_id": item.asset_id,
            "filename": item.filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
        },
        None,
    )


@app.command("search-hot")
def search_hot(
    query: str = typer.Option(..., "--query", "-q"),
    time_range: str = typer.Option("7d", "--time-range"),
    limit: int = typer.Option(30, "--limit"),
    provider: list[str] = typer.Option([], "--provider"),
    web_results: Path | None = typer.Option(
        None, "--web-results", help="JSON 文件：宿主 websearch 结果数组 [{url,title,...}]"
    ),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    async def run():
        hits = None
        if web_results is not None:
            hits = json.loads(web_results.read_text(encoding="utf-8"))
        try:
            report = await ResearchService().search_hot_notes(
                SearchQuery(query=query, time_range=time_range, limit=limit),
                providers=provider or None,
                web_results=hits,
            )
        except ClientWebSearchRequired as exc:
            _emit_needs_web(exc, output)
            raise typer.Exit(code=2) from exc
        payload = report.model_dump(mode="json")
        _emit("search_hot_notes", payload, output)

    asyncio.run(run())


@app.command("generate")
def generate(
    topic: str = typer.Option(..., "--topic"),
    objective: str = typer.Option("search_growth", "--objective"),
    format_: str = typer.Option("graphic", "--format"),
    target_audience: str | None = typer.Option(None, "--audience"),
    research_current: bool = typer.Option(True, "--research-current/--no-research-current"),
    search_provider: list[str] = typer.Option([], "--search-provider"),
    web_results: Path | None = typer.Option(
        None, "--web-results", help="JSON 文件：宿主 websearch 结果数组"
    ),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    async def run():
        hits = None
        if web_results is not None:
            hits = json.loads(web_results.read_text(encoding="utf-8"))
        try:
            package = await ContentWorkflow().run(
                GenerateRequest(
                    topic=topic,
                    objective=objective,
                    format=format_,
                    target_audience=target_audience,
                    research_current_trends=research_current,
                    web_results=hits or [],
                ),
                search_providers=search_provider or None,
                web_results=hits,
            )
        except ClientWebSearchRequired as exc:
            _emit_needs_web(exc, output)
            raise typer.Exit(code=2) from exc
        data = package.model_dump(mode="json")
        from xhs_skill.generation.creation_bundle import build_creation_bundle

        data["creation_bundle"] = build_creation_bundle(package)
        _emit("generate_xhs_note", data, output)

    asyncio.run(run())


@app.command("pipeline")
def pipeline(
    topic: str = typer.Option(..., "--topic"),
    provider: str = typer.Option("fixture", "--provider"),
    output: Path = typer.Option(Path("output/package.json"), "--output"),
) -> None:
    async def run():
        package = await ContentWorkflow().run(
            GenerateRequest(topic=topic),
            search_providers=[provider],
        )
        data = package.model_dump(mode="json")
        from xhs_skill.generation.creation_bundle import build_creation_bundle

        data["creation_bundle"] = build_creation_bundle(package)
        _emit("generate_xhs_note", data, output)

    asyncio.run(run())


@app.command("diagnose")
def diagnose(input_: Path = typer.Option(..., "--input")) -> None:
    from xhs_skill.generation.diagnose_structure import structure_checks
    from xhs_skill.verifiers import ai_style_report, check_text, originality_report

    text = input_.read_text(encoding="utf-8")
    structure = structure_checks(title="", body=text)
    _emit(
        "diagnose_xhs_note",
        {
            "compliance": check_text(text),
            "originality": originality_report(text, []),
            "ai_style": ai_style_report(text),
            "structure_checks": structure,
            "recommended_fixes": structure.get("recommended_fixes") or [],
        },
        None,
    )


@account_app.command("weight")
def account_weight(
    account_id: str = typer.Option(..., "--account"),
    input_: Path | None = typer.Option(None, "--input"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    analytics = None
    if input_:
        analytics = AccountAnalytics.model_validate_json(input_.read_text(encoding="utf-8"))
    report = AccountService().query_weight(account_id, analytics)
    _emit("query_account_weight", report.model_dump(mode="json"), output)


@account_app.command("login")
def account_login(
    account_id: str = typer.Option(..., "--account"),
    timeout_seconds: int = typer.Option(180, "--timeout"),
) -> None:
    async def run():
        flow = LoginFlow()
        status = await flow.start(account_id)
        _emit("start_account_login", status.model_dump(mode="json"), None)
        typer.echo("请在打开的浏览器中扫码并确认。此命令会等待登录完成。")
        elapsed = 0
        while elapsed < timeout_seconds:
            await asyncio.sleep(2)
            elapsed += 2
            status = await flow.status(account_id)
            if status.status in {"AUTHENTICATED", "RISK_VERIFICATION_REQUIRED", "ACCOUNT_MISMATCH"}:
                _emit("check_account_login", status.model_dump(mode="json"), None)
                return
        typer.echo("登录等待超时；未保存未认证会话。", err=True)

    asyncio.run(run())


@account_app.command("status")
def account_status(account_id: str = typer.Option(..., "--account")) -> None:
    async def run():
        _emit(
            "check_account_login",
            (await LoginFlow().status(account_id)).model_dump(mode="json"),
            None,
        )

    asyncio.run(run())


@account_app.command("logout")
def account_logout(
    account_id: str = typer.Option(..., "--account"),
    delete_session: bool = typer.Option(True, "--delete-session/--keep-session"),
) -> None:
    async def run():
        _emit(
            "logout_account",
            (
                await LoginFlow().logout(account_id, delete_session=delete_session)
            ).model_dump(mode="json"),
            None,
        )

    asyncio.run(run())


@publish_app.command("draft")
def publish_draft(
    account_id: str = typer.Option(..., "--account"),
    package_path: Path = typer.Option(..., "--package"),
    mode: PublishMode = typer.Option(PublishMode.REQUIRE_CONFIRMATION, "--mode"),
) -> None:
    from xhs_skill.schemas.content import DeliveryPackage

    package = DeliveryPackage.model_validate_json(package_path.read_text(encoding="utf-8"))
    draft = PublishingService().create_draft(account_id, package, mode)
    _emit("create_publish_draft", draft.model_dump(mode="json"), None)


@publish_app.command("preview")
def publish_preview(draft_id: str = typer.Option(..., "--draft")) -> None:
    async def run():
        _emit(
            "preview_publish_draft",
            (await PublishingService().preview(draft_id)).model_dump(mode="json"),
            None,
        )

    asyncio.run(run())


@publish_app.command("canary")
def publish_canary(
    account_id: str = typer.Option(..., "--account"),
    tenant_id: str = typer.Option("local", "--tenant"),
) -> None:
    """探测创作者中心发布页关键选择器是否仍可用。"""

    async def run() -> None:
        result = await PublishingService().check_selector_health(account_id, tenant_id)
        _emit("publish_canary", result if isinstance(result, dict) else {"result": result}, None)
        if not result.get("ok"):
            raise typer.Exit(code=2)

    asyncio.run(run())


@publish_app.command("approve")
def publish_approve(
    draft_id: str = typer.Option(..., "--draft"),
    ai_disclosure_confirmed: bool = typer.Option(False, "--confirm-ai-disclosure"),
    commercial_disclosure_confirmed: bool = typer.Option(
        False, "--confirm-commercial-disclosure"
    ),
    account_identity_confirmed: bool = typer.Option(False, "--confirm-account"),
) -> None:
    approval = PublishingService().approve(
        draft_id,
        ai_disclosure_confirmed=ai_disclosure_confirmed,
        commercial_disclosure_confirmed=commercial_disclosure_confirmed,
        account_identity_confirmed=account_identity_confirmed,
    )
    _emit("approve_publish_draft", approval.model_dump(mode="json"), None)


@publish_app.command("execute")
def publish_execute(
    draft_id: str = typer.Option(..., "--draft"),
    approval_token: str = typer.Option(..., "--approval-token"),
) -> None:
    async def run():
        _emit(
            "publish_note",
            (await PublishingService().publish(draft_id, approval_token)).model_dump(mode="json"),
            None,
        )

    asyncio.run(run())


@publish_app.command("schedule")
def publish_schedule(
    draft_id: str = typer.Option(..., "--draft"),
    approval_token: str = typer.Option(..., "--approval-token"),
    at: str = typer.Option(..., "--at"),
) -> None:
    async def run() -> None:
        scheduled_at = datetime.fromisoformat(at)
        schedule = await PublishingService().schedule(draft_id, approval_token, scheduled_at)
        _emit("schedule_note", schedule.model_dump(mode="json"), None)

    asyncio.run(run())


@publish_app.command("scheduler-worker")
def publish_scheduler_worker() -> None:
    async def run() -> None:
        await PublishingService().run_scheduler_worker()

    asyncio.run(run())


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    workers: int | None = typer.Option(None, "--workers"),
) -> None:
    worker_count = workers or get_settings().uvicorn_workers
    uvicorn.run(
        "xhs_skill.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=worker_count,
        proxy_headers=True,
    )


@app.command("worker")
def worker(consumer_name: str | None = typer.Option(None, "--consumer-name")) -> None:
    """Run a durable Redis Streams job worker with graceful signal handling."""

    async def run() -> None:
        service = JobService()
        loop = asyncio.get_running_loop()
        for signal_name in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(
                    signal_name, lambda: asyncio.create_task(service.shutdown())
                )
            except NotImplementedError:
                pass
        try:
            await service.run_worker(consumer_name)
        finally:
            await service.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    app()
