-- v5.1 distributed consistency, intelligence evidence and operations loop.
ALTER TABLE enterprise_publish_state
    ADD COLUMN IF NOT EXISTS cancellation_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_token TEXT,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error JSONB;

ALTER TABLE enterprise_outbox
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS last_error JSONB,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS enterprise_job_control (
    tenant_id TEXT NOT NULL REFERENCES enterprise_tenants(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL,
    state TEXT NOT NULL,
    cancel_epoch BIGINT NOT NULL DEFAULT 0,
    cancel_requested_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, job_id)
);

CREATE TABLE IF NOT EXISTS enterprise_dead_letters (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    error JSONB NOT NULL,
    attempts INTEGER NOT NULL,
    replay_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at TIMESTAMPTZ,
    UNIQUE (tenant_id, source, source_id)
);
CREATE INDEX IF NOT EXISTS enterprise_dead_letters_open_idx
    ON enterprise_dead_letters(tenant_id, status, created_at)
    WHERE status IN ('OPEN', 'REPLAYING');

CREATE TABLE IF NOT EXISTS published_note_metrics (
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, note_id, snapshot_at)
);
CREATE INDEX IF NOT EXISTS published_note_metrics_account_idx
    ON published_note_metrics(tenant_id, account_id, snapshot_at);


CREATE TABLE IF NOT EXISTS account_profiles (
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, account_id)
);

CREATE TABLE IF NOT EXISTS account_weight_snapshots (
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    score NUMERIC(8,4),
    payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, account_id, recorded_at)
);

CREATE TABLE IF NOT EXISTS content_calendar_items (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS content_calendar_due_idx
    ON content_calendar_items(tenant_id, status, scheduled_at);

CREATE TABLE IF NOT EXISTS content_series_plans (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS content_experiments (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    primary_metric TEXT NOT NULL,
    payload JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS content_experiment_assignments (
    tenant_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, experiment_id, subject_id)
);

CREATE TABLE IF NOT EXISTS content_experiment_outcomes (
    tenant_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, experiment_id, subject_id, metric, recorded_at)
);

CREATE TABLE IF NOT EXISTS contextual_bandit_state (
    tenant_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    arm_id TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    pulls BIGINT NOT NULL DEFAULT 0,
    a_matrix JSONB NOT NULL,
    b_vector JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, policy_id, arm_id)
);

CREATE TABLE IF NOT EXISTS content_asset_library (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, sha256)
);


CREATE TABLE IF NOT EXISTS post_publish_sync_tasks (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    note_url TEXT,
    due_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS post_publish_sync_due_idx
    ON post_publish_sync_tasks(tenant_id, status, due_at);

CREATE TABLE IF NOT EXISTS content_retrospectives (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

ALTER TABLE enterprise_job_control ENABLE ROW LEVEL SECURITY;
ALTER TABLE enterprise_dead_letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE published_note_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_weight_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_calendar_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_series_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_experiment_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_experiment_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE contextual_bandit_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_asset_library ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_retrospectives ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_publish_sync_tasks ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'enterprise_job_control','enterprise_dead_letters','published_note_metrics',
        'account_weight_snapshots','account_profiles','content_calendar_items','content_series_plans',
        'content_experiments','content_experiment_assignments','content_experiment_outcomes',
        'contextual_bandit_state','content_asset_library','content_retrospectives',
        'post_publish_sync_tasks'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_' || table_name
        ) THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
                'tenant_isolation_' || table_name,
                table_name
            );
        END IF;
    END LOOP;
END $$;
