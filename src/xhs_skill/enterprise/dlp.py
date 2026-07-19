from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DLPFinding:
    kind: str
    start: int
    end: int
    severity: str
    redacted: str


_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("EMAIL", "MEDIUM", re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")),
    ("CN_MOBILE", "MEDIUM", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("CN_ID", "HIGH", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")),
    ("BANK_CARD", "HIGH", re.compile(r"(?<!\d)(?:\d[ -]?){15,19}(?!\d)")),
    ("PRIVATE_KEY", "CRITICAL", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GENERIC_API_KEY", "HIGH", re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}")),
]


def scan_text(text: str) -> list[DLPFinding]:
    findings: list[DLPFinding] = []
    for kind, severity, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if kind == "EMAIL":
                local, _, domain = value.partition("@")
                redacted = f"{local[:1]}***@{domain}"
            else:
                redacted = value[:2] + "***" + value[-2:] if len(value) > 6 else "***"
            findings.append(DLPFinding(kind, match.start(), match.end(), severity, redacted))
    return sorted(findings, key=lambda item: (item.start, item.end))


def redact_text(text: str) -> tuple[str, list[DLPFinding]]:
    findings = scan_text(text)
    redacted = text
    for item in reversed(findings):
        redacted = redacted[: item.start] + item.redacted + redacted[item.end :]
    return redacted, findings


def contains_blocking_secret(text: str) -> bool:
    return any(item.severity == "CRITICAL" or item.kind == "GENERIC_API_KEY" for item in scan_text(text))
