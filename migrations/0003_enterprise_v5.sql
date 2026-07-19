-- Enterprise v5 state, SCIM, budgets, audit checkpoints and transactional outbox.
CREATE TABLE IF NOT EXISTS enterprise_tenants (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL,
    plan TEXT NOT NULL,
    policy JSONB NOT NULL,
    domains JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS enterprise_users (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    payload JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    external_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, user_name),
    UNIQUE NULLS NOT DISTINCT (tenant_id, external_id)
);

CREATE TABLE IF NOT EXISTS enterprise_groups (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    payload JSONB NOT NULL,
    external_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE NULLS NOT DISTINCT (tenant_id, external_id)
);

CREATE TABLE IF NOT EXISTS enterprise_usage_ledger (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    estimated_cost_usd NUMERIC(18,8) NOT NULL,
    actual_cost_usd NUMERIC(18,8),
    provider TEXT,
    model TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS enterprise_usage_ledger_period_idx
    ON enterprise_usage_ledger (tenant_id, created_at, status);

CREATE TABLE IF NOT EXISTS enterprise_approvals (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS enterprise_approvals_resource_idx
    ON enterprise_approvals (tenant_id, resource_type, resource_id, state);

CREATE TABLE IF NOT EXISTS enterprise_publish_state (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    state TEXT NOT NULL,
    payload JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    publish_fingerprint TEXT,
    version BIGINT NOT NULL DEFAULT 1,
    scheduled_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE NULLS NOT DISTINCT (tenant_id, account_id, publish_fingerprint)
);
CREATE INDEX IF NOT EXISTS enterprise_publish_due_idx
    ON enterprise_publish_state (state, scheduled_at)
    WHERE state = 'SCHEDULED';

CREATE TABLE IF NOT EXISTS enterprise_outbox (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS enterprise_outbox_claim_idx
    ON enterprise_outbox (status, available_at, id)
    WHERE status IN ('PENDING', 'RETRY');

CREATE TABLE IF NOT EXISTS enterprise_audit_checkpoints (
    tenant_id TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    root_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    object_uri TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, sequence)
);

ALTER TABLE enterprise_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_publish_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_audit_checkpoints ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_tenants') THEN
        CREATE POLICY tenant_isolation_tenants ON enterprise_tenants
            USING (id = current_setting('app.tenant_id', true))
            WITH CHECK (id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_users') THEN
        CREATE POLICY tenant_isolation_users ON enterprise_users
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_groups') THEN
        CREATE POLICY tenant_isolation_groups ON enterprise_groups
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_usage') THEN
        CREATE POLICY tenant_isolation_usage ON enterprise_usage_ledger
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_approvals') THEN
        CREATE POLICY tenant_isolation_approvals ON enterprise_approvals
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_publish') THEN
        CREATE POLICY tenant_isolation_publish ON enterprise_publish_state
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_outbox') THEN
        CREATE POLICY tenant_isolation_outbox ON enterprise_outbox
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_audit_checkpoints') THEN
        CREATE POLICY tenant_isolation_audit_checkpoints ON enterprise_audit_checkpoints
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END $$;
