from __future__ import annotations

from pathlib import Path

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.schemas.research import SearchResult
from xhs_skill.search.authorized_import import AuthorizedImportProvider
from xhs_skill.search.base import SearchProvider
from xhs_skill.search.bing import BingSearchProvider
from xhs_skill.search.brave import BraveSearchProvider
from xhs_skill.search.client_web import ClientWebSearchProvider
from xhs_skill.search.fixture import FixtureSearchProvider
from xhs_skill.search.google_cse import GoogleCustomSearchProvider
from xhs_skill.search.manual import ManualURLProvider
from xhs_skill.search.openai_web import OpenAIWebSearchProvider
from xhs_skill.search.searxng import SearxNGSearchProvider


class SearchRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._providers: dict[str, SearchProvider] = {
            "fixture": FixtureSearchProvider(),
            "client_web": ClientWebSearchProvider(),
        }
        if self.settings.brave_search_api_key:
            self._providers["brave"] = BraveSearchProvider(
                self.settings.brave_search_api_key, self.settings.brave_search_base_url
            )
        if self.settings.bing_search_api_key:
            self._providers["bing"] = BingSearchProvider(
                self.settings.bing_search_api_key, self.settings.bing_search_base_url
            )
        if self.settings.google_search_api_key and self.settings.google_search_cx:
            self._providers["google_cse"] = GoogleCustomSearchProvider(
                self.settings.google_search_api_key,
                self.settings.google_search_cx,
                self.settings.google_search_base_url,
            )
        if self.settings.searxng_base_url:
            self._providers["searxng"] = SearxNGSearchProvider(self.settings.searxng_base_url)
        if self.settings.openai_api_key and self.settings.openai_default_model:
            self._providers["openai_web"] = OpenAIWebSearchProvider(
                self.settings.openai_api_key,
                self.settings.openai_base_url,
                self.settings.openai_default_model,
            )

    def register(self, provider: SearchProvider) -> None:
        self._providers[provider.name] = provider

    def configure_authorized_import(self, path: str | Path) -> None:
        self._providers["authorized_import"] = AuthorizedImportProvider(path)

    def configure_manual(self, urls: list[str]) -> None:
        self._providers["manual"] = ManualURLProvider(urls)

    def configure_client_web(self, results: list[SearchResult]) -> None:
        self._providers["client_web"] = ClientWebSearchProvider(results)

    def get(self, name: str) -> SearchProvider:
        return self._providers[name]

    def list(self) -> list[str]:
        return sorted(self._providers)
