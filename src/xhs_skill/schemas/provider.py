from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelCapabilities(BaseModel):
    text: bool = True
    vision: bool = False
    audio_input: bool = False
    audio_output: bool = False
    video_input: bool = False
    streaming: bool = False
    tool_calling: bool = False
    parallel_tool_calls: bool = False
    structured_output: bool = False
    json_mode: bool = False
    reasoning: bool = False
    embeddings: bool = False
    reranking: bool = False
    web_search: bool = False
    url_fetch: bool = False
    code_execution: bool = False
    prompt_cache: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None


class ModelInfo(BaseModel):
    provider: str
    id: str
    display_name: str | None = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model: str
    system: str
    prompt: str
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    temperature: float = 0.5
    max_output_tokens: int = 4096
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationResponse(BaseModel):
    text: str
    data: dict[str, Any] | None = None
    provider: str
    model: str
    request_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class ModelEvent(BaseModel):
    type: str
    delta: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
