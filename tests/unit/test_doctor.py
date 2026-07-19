"""Doctor 就绪诊断。"""
from xhs_skill.core.config import Settings
from xhs_skill.core.doctor import run_doctor


def _settings(**kwargs) -> Settings:
    base = dict(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        deployment_profile="personal",
        model_providers_file="/dev/null",
        xhs_selector_config="/dev/null",
        xhs_accounts_config="/dev/null",
        xhs_session_dir="/tmp/test-sessions",
        xhs_screenshot_dir="/tmp/test-screenshots",
        object_storage_dir="/tmp/test-objects",
        enterprise_data_dir="/tmp/test-enterprise",
        image_provider="noop",
    )
    base.update(kwargs)
    return Settings(**base)


def test_doctor_report_structure(tmp_path):
    # 写一个最小 selector 文件
    sel = tmp_path / "sel.yaml"
    sel.write_text("publish: {}\n", encoding="utf-8")
    report = run_doctor(_settings(xhs_selector_config=sel))
    assert "version" in report
    assert "checks" in report
    assert "summary" in report
    assert "golden_path" in report
    names = {item["name"] for item in report["checks"]}
    assert "import_path" in names
    assert "hybrid_ranker" in names
    assert "cross_encoder" in names
    assert "bandit" in names
    assert "ltr_feature_schema" in names
    assert "publication_gate" in names
    gate = next(item for item in report["checks"] if item["name"] == "publication_gate")
    assert gate["ok"] is True
    # personal 无 model key 时仍应 ready（error=0），最多 warn
    assert report["summary"]["errors"] == 0
    assert report["ready"] is True