from __future__ import annotations

import re

from xhs_skill.schemas.content import CommercialStatus, DeliveryPackage

CRITICAL_PATTERNS = {
    "ABSOLUTE_CLAIM": re.compile(r"100%|绝对安全|全网第一|唯一|永久有效"),
    "MEDICAL_CLAIM": re.compile(r"治疗|治愈|根治|药到病除|保证减重"),
    "FAKE_EXPERIENCE": re.compile(r"亲测\d+天|用了\d+个月|朋友都来问"),
    "FAKE_FEEDBACK": re.compile(r"用户都说|万人好评|零差评"),
    "ILLEGAL_DIVERSION": re.compile(r"加V|加微信|私信发联系方式|扫码进群"),
}


def check_text(
    text: str, commercial_status: CommercialStatus = CommercialStatus.NON_COMMERCIAL
) -> dict:
    findings = []
    for code, pattern in CRITICAL_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            findings.append({"code": code, "matches": matches, "severity": "CRITICAL"})
    if (
        commercial_status != CommercialStatus.NON_COMMERCIAL
        and "合作" not in text
        and "品牌" not in text
    ):
        findings.append({"code": "COMMERCIAL_DISCLOSURE_REVIEW", "severity": "HIGH"})
    critical = any(item["severity"] == "CRITICAL" for item in findings)
    return {
        "passed": not critical,
        "findings": findings,
        "publication_status": "BLOCKED" if critical else "HUMAN_REVIEW_REQUIRED",
    }


def check_package(package: DeliveryPackage, commercial_status: CommercialStatus) -> dict:
    return check_text(f"{package.selected_title}\n{package.body}", commercial_status)
