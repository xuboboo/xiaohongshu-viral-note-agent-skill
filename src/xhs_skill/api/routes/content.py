from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from xhs_skill.api.dependencies import (
    account_service,
    asset_store,
    content_workflow,
    generation_service,
)
from xhs_skill.api.security import require_scopes
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.costs import get_cost_budget_service
from xhs_skill.enterprise.enforcement import enforce_enterprise_policy
from xhs_skill.enterprise.quota import BudgetExceededError
from xhs_skill.generation.diagnose_structure import structure_checks
from xhs_skill.schemas.content import DeliveryPackage, GenerateRequest
from xhs_skill.schemas.research import HotNotesReport
from xhs_skill.search.adaptive import ClientWebSearchRequired
from xhs_skill.verifiers import ai_style_report, check_text, originality_report_async

router = APIRouter(prefix="/v1/content", tags=["content"])


class DiagnoseRequest(BaseModel):
    title: str = ""
    body: str
    references: list[str] = Field(default_factory=list, max_length=200)
    candidate_image_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    reference_image_asset_ids: list[str] = Field(default_factory=list, max_length=100)


class RewriteRequest(BaseModel):
    body: str
    title: str = ""
    commercial_status: str = "NON_COMMERCIAL"
    constraints: list[str] = Field(default_factory=list, max_length=20)
    references: list[str] = Field(default_factory=list, max_length=200)


class ReplyDraftRequest(BaseModel):
    """授权评论回复草稿：仅生成，永不自动提交。"""

    original_comment: str = Field(min_length=1, max_length=2000)
    note_context: str = Field(default="", max_length=2000)
    tone: str = Field(default="helpful", max_length=32)
    comment_id: str | None = None
    note_id: str | None = None
    max_candidates: int = Field(default=3, ge=1, le=5)


class HotToNoteRequest(BaseModel):
    """热门→选题→一键生成。"""

    query: str = Field(min_length=1, max_length=200)
    suggestion_index: int = Field(default=0, ge=0, le=20)
    suggestion_topic: str | None = Field(default=None, max_length=200)
    dry_run: bool = False
    use_account_health: bool = False
    format: str = Field(default="graphic", pattern="^(graphic|video)$")
    video_duration_seconds: int | None = Field(default=None, ge=15, le=60)
    note_style: str | None = None
    narrative_framework: str | None = None
    target_audience: str | None = None
    commercial_status: str | None = None
    account_id: str | None = None
    brand_voice: dict = Field(default_factory=dict)
    product: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    provider: str | None = None
    providers: list[str] | None = None
    web_results: list[dict] = Field(default_factory=list)


def _resolve_image_assets(tenant_id: str, asset_ids: list[str]) -> list[str]:
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    store = asset_store()
    return [str(store.resolve(tenant_id, asset_id, allowed_types=allowed)) for asset_id in asset_ids]


@router.post("/generate", response_model=DeliveryPackage)
async def generate(
    request: GenerateRequest,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> DeliveryPackage:
    settings = get_settings()
    enforce_enterprise_policy(principal, "content.generate", context={"provider": request.provider})
    reservation = None
    if settings.enterprise_cost_enforcement:
        try:
            reservation = await get_cost_budget_service().reserve(
                tenant_id=principal.tenant_id,
                operation="content.generate",
                estimated_cost_usd=0.15,
                provider=request.provider,
                model=request.model,
                metadata={"topic_length": len(request.topic)},
            )
        except BudgetExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        package = await content_workflow().run(request, tenant_id=principal.tenant_id)
    except ClientWebSearchRequired as exc:
        if reservation:
            await get_cost_budget_service().release(
                principal.tenant_id,
                reservation["id"] if isinstance(reservation, dict) else reservation.id,
            )
        raise HTTPException(status_code=409, detail=exc.to_payload()) from exc
    except Exception:
        if reservation:
            await get_cost_budget_service().release(principal.tenant_id, reservation["id"] if isinstance(reservation, dict) else reservation.id)
        raise
    if reservation:
        await get_cost_budget_service().settle(principal.tenant_id, reservation["id"] if isinstance(reservation, dict) else reservation.id, 0.15)
        package.quality_report["cost_reservation_id"] = reservation["id"] if isinstance(reservation, dict) else reservation.id
    return package


@router.post("/generate-with-research", response_model=DeliveryPackage)
async def generate_with_research(
    request: GenerateRequest,
    report: HotNotesReport,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> DeliveryPackage:
    settings = get_settings()
    enforce_enterprise_policy(principal, "content.generate", context={"provider": request.provider})
    reservation = None
    if settings.enterprise_cost_enforcement:
        try:
            reservation = await get_cost_budget_service().reserve(
                tenant_id=principal.tenant_id,
                operation="content.generate_with_research",
                estimated_cost_usd=0.15,
                provider=request.provider,
                model=request.model,
            )
        except BudgetExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        package = await generation_service().generate(request, report, tenant_id=principal.tenant_id)
    except Exception:
        if reservation:
            await get_cost_budget_service().release(principal.tenant_id, reservation["id"] if isinstance(reservation, dict) else reservation.id)
        raise
    if reservation:
        await get_cost_budget_service().settle(principal.tenant_id, reservation["id"] if isinstance(reservation, dict) else reservation.id, 0.15)
        package.quality_report["cost_reservation_id"] = reservation["id"] if isinstance(reservation, dict) else reservation.id
    return package


@router.post("/generate-from-hot")
async def generate_from_hot(
    payload: HotToNoteRequest,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> dict:
    """热门→选题→一键生成（dry_run 可只选题）。"""
    from xhs_skill.orchestrator.hot_to_note import run_hot_to_note

    enforce_enterprise_policy(principal, "content.generate", context={"provider": payload.provider})
    try:
        return await run_hot_to_note(
            content_workflow(),
            query=payload.query,
            suggestion_index=payload.suggestion_index,
            suggestion_topic=payload.suggestion_topic,
            dry_run=payload.dry_run,
            providers=payload.providers,
            web_results=payload.web_results or None,
            tenant_id=principal.tenant_id,
            format=payload.format,
            video_duration_seconds=payload.video_duration_seconds,
            account_id=payload.account_id,
            use_account_health=payload.use_account_health,
            target_audience=payload.target_audience,
            commercial_status=payload.commercial_status,
            brand_voice=payload.brand_voice or None,
            product=payload.product or None,
            constraints=payload.constraints or None,
            note_style=payload.note_style,
            narrative_framework=payload.narrative_framework,
            provider=payload.provider,
            accounts_service=account_service(),
        )
    except ClientWebSearchRequired as exc:
        raise HTTPException(status_code=409, detail=exc.to_payload()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/diagnose")
async def diagnose(
    payload: DiagnoseRequest,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> dict:
    candidate_images = _resolve_image_assets(
        principal.tenant_id, payload.candidate_image_asset_ids
    )
    reference_images = _resolve_image_assets(
        principal.tenant_id, payload.reference_image_asset_ids
    )
    structure = structure_checks(title=payload.title, body=payload.body)
    return {
        "compliance": check_text(f"{payload.title}\n{payload.body}"),
        "originality": await originality_report_async(
            payload.body,
            payload.references,
            candidate_images=candidate_images,
            reference_images=reference_images,
            candidate_image_labels=payload.candidate_image_asset_ids,
            reference_image_labels=payload.reference_image_asset_ids,
        ),
        "ai_style": ai_style_report(payload.body),
        "structure_checks": structure,
        "recommended_fixes": structure["recommended_fixes"]
        or [
            "增加具体场景、限制条件和不适合人群",
            "删除无法验证的数据和效果承诺",
        ],
    }


@router.post("/rewrite")
async def rewrite(
    payload: RewriteRequest,
    principal: Principal = Depends(require_scopes("content:generate")),
) -> dict:
    gs = generation_service()
    return await gs.rewrite(
        body=payload.body,
        title=payload.title,
        commercial_status=payload.commercial_status,
        constraints=payload.constraints,
        references=payload.references,
        tenant_id=principal.tenant_id,
    )


@router.post("/reply-draft")
async def reply_draft(
    payload: ReplyDraftRequest,
    _: Principal = Depends(require_scopes("content:generate")),
) -> dict:
    """生成授权评论回复草稿；auto_submit 恒为 false。"""
    from xhs_skill.generation.reply_draft import (
        build_authorized_reply_drafts,
        reply_draft_to_dict,
    )

    draft = build_authorized_reply_drafts(
        payload.original_comment,
        note_context=payload.note_context,
        tone=payload.tone,
        comment_id=payload.comment_id,
        note_id=payload.note_id,
        max_candidates=payload.max_candidates,
    )
    return reply_draft_to_dict(draft)
