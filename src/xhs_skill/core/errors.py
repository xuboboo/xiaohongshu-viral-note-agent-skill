from __future__ import annotations


class XHSSkillError(Exception):
    """Base error with a stable machine-readable code."""

    code = "XHS_SKILL_ERROR"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(XHSSkillError):
    code = "CONFIGURATION_ERROR"


class ProviderError(XHSSkillError):
    code = "PROVIDER_ERROR"
    status_code = 502


class SearchError(XHSSkillError):
    code = "SEARCH_ERROR"
    status_code = 502


class AuthenticationRequiredError(XHSSkillError):
    code = "LOGIN_REQUIRED"
    status_code = 401


class HumanApprovalRequiredError(XHSSkillError):
    code = "HUMAN_APPROVAL_REQUIRED"
    status_code = 409


class PublishBlockedError(XHSSkillError):
    code = "PUBLISH_BLOCKED"
    status_code = 409


class UnsupportedUIVersionError(XHSSkillError):
    code = "UI_VERSION_UNSUPPORTED"
    status_code = 409


class OverloadedError(XHSSkillError):
    code = "OVERLOADED"
    status_code = 503


class RateLimitExceededError(XHSSkillError):
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


class CircuitOpenError(XHSSkillError):
    code = "CIRCUIT_OPEN"
    status_code = 503


class QueueFullError(XHSSkillError):
    code = "JOB_QUEUE_FULL"
    status_code = 503
