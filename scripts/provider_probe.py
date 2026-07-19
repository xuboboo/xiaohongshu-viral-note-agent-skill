from __future__ import annotations

import argparse
import asyncio
import json

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.providers import ProviderRegistry  # noqa: E402


async def run(name: str | None) -> None:
    registry = ProviderRegistry()
    names = [name] if name else registry.list()
    reports = []
    for provider_name in names:
        provider = registry.get(provider_name)
        models = await provider.list_models()
        reports.append({
            "provider": provider_name,
            "models": [item.model_dump(mode="json") for item in models],
        })
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="探测已配置模型 Provider 能力")
    parser.add_argument("--provider")
    asyncio.run(run(parser.parse_args().provider))
