-- Query paths used by workers, dashboards, replay, and idempotent publication.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tasks_status_created
  ON tasks(status, created_at ASC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tasks_tenant_status_updated
  ON tasks(tenant_id, status, updated_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stream_events_created_brin
  ON stream_events USING brin(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_search_results_query_provider_created
  ON search_results(query, source_provider, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_account_analytics_account_period
  ON xhs_account_analytics(account_id, period_end DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_account_weight_account_created
  ON xhs_account_weight_snapshots(account_id, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_auth_sessions_account_status
  ON xhs_auth_sessions(account_id, session_status, expires_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_publish_approvals_draft_expires
  ON publish_approvals(draft_id, expires_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_publish_jobs_status_scheduled
  ON publish_jobs(status, scheduled_at ASC)
  WHERE status IN ('PENDING', 'SCHEDULED', 'RUNNING');
