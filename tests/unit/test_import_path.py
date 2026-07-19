"""安装路径防护：不应从 build/lib 加载。"""
from pathlib import Path

import xhs_skill


def test_package_not_from_build_lib():
    path = Path(xhs_skill.__file__).resolve()
    parts = path.parts
    assert not ("build" in parts and "lib" in parts)
    # 开发树通常在 src/xhs_skill
    assert path.name == "__init__.py"