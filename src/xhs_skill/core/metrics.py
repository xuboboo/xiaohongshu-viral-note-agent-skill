from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUESTS = Counter(
    "xhs_http_requests_total",
    "HTTP requests",
    ["method", "status_class"],
)
REQUEST_DURATION = Histogram(
    "xhs_http_request_duration_seconds",
    "HTTP request duration",
    ["method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
INFLIGHT = Gauge("xhs_http_inflight_requests", "In-flight HTTP requests")
OVERLOADS = Counter("xhs_overload_rejections_total", "Rejected requests", ["code"])
JOB_QUEUE = Gauge("xhs_job_queue_depth", "Queued background jobs")
ACTIVE_JOBS = Gauge("xhs_active_jobs", "Running background jobs")


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
