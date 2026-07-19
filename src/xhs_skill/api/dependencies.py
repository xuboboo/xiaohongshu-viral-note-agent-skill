from __future__ import annotations

from functools import lru_cache

from xhs_skill.accounts import AccountService
from xhs_skill.accounts.browser_sync import BrowserAnalyticsSync
from xhs_skill.browser import LoginFlow
from xhs_skill.generation import GenerationService
from xhs_skill.jobs import JobService
from xhs_skill.operations import OperationsService
from xhs_skill.orchestrator import ContentWorkflow
from xhs_skill.providers import ProviderRegistry
from xhs_skill.publishing import PublishingService
from xhs_skill.research import ResearchService
from xhs_skill.search import SearchRegistry
from xhs_skill.storage.assets import AssetStore


@lru_cache(maxsize=1)
def search_registry() -> SearchRegistry:
    return SearchRegistry()


@lru_cache(maxsize=1)
def provider_registry() -> ProviderRegistry:
    return ProviderRegistry()


@lru_cache(maxsize=1)
def research_service() -> ResearchService:
    return ResearchService(search_registry())


@lru_cache(maxsize=1)
def generation_service() -> GenerationService:
    return GenerationService(provider_registry())


@lru_cache(maxsize=1)
def content_workflow() -> ContentWorkflow:
    return ContentWorkflow(research_service(), generation_service())


@lru_cache(maxsize=1)
def account_service() -> AccountService:
    return AccountService()


@lru_cache(maxsize=1)
def login_flow() -> LoginFlow:
    return LoginFlow()


@lru_cache(maxsize=1)
def publishing_service() -> PublishingService:
    return PublishingService(login_flow=login_flow())


@lru_cache(maxsize=1)
def job_service() -> JobService:
    return JobService()


@lru_cache(maxsize=1)
def browser_analytics_sync() -> BrowserAnalyticsSync:
    return BrowserAnalyticsSync(login_flow())


@lru_cache(maxsize=1)
def asset_store() -> AssetStore:
    return AssetStore()


@lru_cache(maxsize=1)
def operations_service() -> OperationsService:
    return OperationsService()
