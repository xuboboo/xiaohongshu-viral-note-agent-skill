-- Reference PostgreSQL schema for production deployments.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS xhs_accounts (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    external_account_id TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0',
    UNIQUE (tenant_id, external_account_id)
);

CREATE TABLE IF NOT EXISTS xhs_auth_sessions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID NOT NULL REFERENCES xhs_accounts(id),
    session_status TEXT NOT NULL,
    encrypted_storage_state BYTEA,
    storage_state_nonce BYTEA,
    encryption_key_version TEXT,
    authenticated_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    last_verified_at TIMESTAMPTZ,
    browser_profile_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS xhs_account_analytics (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID NOT NULL REFERENCES xhs_accounts(id),
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS xhs_account_weight_snapshots (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID NOT NULL REFERENCES xhs_accounts(id),
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input JSONB NOT NULL,
    result JSONB,
    error JSONB,
    trace_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS stream_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    task_id UUID NOT NULL REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    payload JSONB NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(task_id, sequence)
);

CREATE TABLE IF NOT EXISTS search_results (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    query TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT,
    payload JSONB NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS delivery_packages (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID REFERENCES xhs_accounts(id),
    content_hash TEXT NOT NULL,
    package JSONB NOT NULL,
    publication_status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS publish_drafts (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID NOT NULL REFERENCES xhs_accounts(id),
    delivery_package_id UUID NOT NULL REFERENCES delivery_packages(id),
    content_hash TEXT NOT NULL,
    publish_mode TEXT NOT NULL,
    preview_object_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS publish_approvals (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    draft_id UUID NOT NULL REFERENCES publish_drafts(id),
    expected_content_hash TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS publish_jobs (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    account_id UUID NOT NULL REFERENCES xhs_accounts(id),
    draft_id UUID NOT NULL REFERENCES publish_drafts(id),
    status TEXT NOT NULL,
    publish_fingerprint TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    note_url TEXT,
    audit JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(account_id, publish_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_stream_events_task_sequence ON stream_events(task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_search_results_canonical ON search_results(canonical_url);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_account_published ON publish_jobs(account_id, published_at DESC);
