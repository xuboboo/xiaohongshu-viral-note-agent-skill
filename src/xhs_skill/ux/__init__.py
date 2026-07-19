"""用户 / Agent 体验层：统一工具返回的可读引导，不改变业务语义。"""

from xhs_skill.ux.catalog import annotate_tool_definition, tools_list_meta
from xhs_skill.ux.envelope import (
    attach_ux,
    enrich_needs_web_search,
    enrich_tool_result,
    ux_for_delivery_package,
    ux_for_hot_to_note,
    ux_for_research,
    ux_for_rewrite,
)

__all__ = [
    "annotate_tool_definition",
    "attach_ux",
    "enrich_needs_web_search",
    "enrich_tool_result",
    "tools_list_meta",
    "ux_for_delivery_package",
    "ux_for_hot_to_note",
    "ux_for_research",
    "ux_for_rewrite",
]