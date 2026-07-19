from __future__ import annotations

from typing import Any

from xhs_skill.generation import GenerationService
from xhs_skill.orchestrator import ContentWorkflow
from xhs_skill.providers import ProviderRegistry
from xhs_skill.research import ResearchService
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.search import SearchRegistry
from xhs_skill.storage.assets import AssetStore


class TaskHandlerRegistry:
    """Serializable distributed job handlers keyed by stable task type."""

    def __init__(self) -> None:
        self.search_registry = SearchRegistry()
        self.research = ResearchService(self.search_registry)
        self.generation = GenerationService(ProviderRegistry())
        self.workflow = ContentWorkflow(self.research, self.generation)
        self.assets = AssetStore()

    async def execute(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        tenant_id: str = "local",
    ) -> dict[str, Any]:
        safe_payload = dict(payload)
        if task_type == "SEARCH_HOT_NOTES":
            sources = safe_payload.pop("sources", None)
            asset_id = safe_payload.pop("authorized_import_asset_id", None)
            web_results = safe_payload.pop("web_results", None)
            research = self.research
            if asset_id:
                path = self.assets.resolve(
                    tenant_id,
                    str(asset_id),
                    allowed_types={"application/json"},
                )
                registry = SearchRegistry()
                registry.configure_authorized_import(path)
                research = ResearchService(registry)
                sources = sources or ["authorized_import"]
            query = SearchQuery.model_validate(safe_payload)
            report = await research.search_hot_notes(
                query,
                providers=sources or None,
                web_results=web_results,
            )
            return report.model_dump(mode="json")
        if task_type == "CREATE_NOTE":
            request = GenerateRequest.model_validate(safe_payload)
            package = await self.workflow.run(
                request,
                tenant_id=tenant_id,
                web_results=request.web_results or None,
            )
            return package.model_dump(mode="json")
        raise ValueError(f"Unsupported distributed task type: {task_type}")
