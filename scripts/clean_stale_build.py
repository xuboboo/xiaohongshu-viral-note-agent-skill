"""清理 setuptools 产生的过时 build/ 并检查 import 是否来自 src。"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    build_dir = root / "build"
    report: dict = {"build_exists": build_dir.is_dir(), "removed": False}

    if build_dir.is_dir() and not args.check_only:
        shutil.rmtree(build_dir, ignore_errors=True)
        report["removed"] = not build_dir.exists()

    # import 路径自检
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        import xhs_skill

        path = Path(xhs_skill.__file__).resolve()
        parts = set(path.parts)
        report["import_path"] = str(path)
        report["from_build_lib"] = "build" in parts and "lib" in parts
        report["from_src"] = "src" in parts
    except Exception as exc:  # noqa: BLE001
        report["import_error"] = f"{type(exc).__name__}: {exc}"

    print(report)
    if report.get("from_build_lib"):
        raise SystemExit(
            "xhs_skill is importing from build/lib — reinstall editable from src:\n"
            "  pip install -e .\n"
            "  python scripts/clean_stale_build.py"
        )
    if build_dir.is_dir() and args.check_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()