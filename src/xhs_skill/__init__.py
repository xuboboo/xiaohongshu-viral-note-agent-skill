"""小红书爆款笔记生成 agent Skill runtime."""

from __future__ import annotations

from pathlib import Path

__version__ = "5.14.5"


def _warn_stale_build_import() -> None:
    """若从 setuptools build/lib 加载，提示改用 editable src 安装。"""
    try:
        parts = set(Path(__file__).resolve().parts)
    except OSError:
        return
    if "build" in parts and "lib" in parts:
        import warnings

        warnings.warn(
            "xhs_skill is imported from build/lib (stale setuptools tree). "
            "Prefer: pip install -e .  and  python scripts/clean_stale_build.py",
            RuntimeWarning,
            stacklevel=2,
        )


_warn_stale_build_import()
