-- Durable state. Redis holds nothing that cannot be rebuilt from here.

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    handle        TEXT UNIQUE NOT NULL,
    -- Persona is per-user and is rendered into the cached system prefix.
    -- Changing it invalidates that user's cache, which is correct and rare.
    persona       JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan          TEXT NOT NULL DEFAULT 'free',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued',
    -- The full API message array. This is what makes a killed worker
    -- resumable: reload it and the next request is byte-identical to the one
    -- that would have been sent.
    messages         JSONB NOT NULL DEFAULT '[]'::jsonb,
    scratch          JSONB NOT NULL DEFAULT '{}'::jsonb,
    iterations       INTEGER NOT NULL DEFAULT 0,
    spend_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0,
    error            TEXT,
    idempotency_key  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every query filters on user_id, so it leads every index.
CREATE INDEX IF NOT EXISTS runs_user_session_idx
    ON runs (user_id, session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runs_status_idx ON runs (status, updated_at)
    WHERE status IN ('queued', 'running');

-- Idempotency as a constraint, not a read-then-write. At 50 concurrent users
-- behind a retrying client, the check-then-insert race happens daily.
CREATE UNIQUE INDEX IF NOT EXISTS runs_idempotency_idx
    ON runs (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS run_events (
    run_id     TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    type       TEXT NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    data       JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS run_events_user_idx ON run_events (user_id, run_id, seq);

-- Cost ledger. Separate from runs so it survives run deletion and can be
-- aggregated per user without touching conversation data.
CREATE TABLE IF NOT EXISTS usage_ledger (
    id                          BIGSERIAL PRIMARY KEY,
    user_id                     TEXT NOT NULL,
    run_id                      TEXT NOT NULL,
    model                       TEXT NOT NULL,
    input_tokens                INTEGER NOT NULL DEFAULT 0,
    output_tokens               INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd                    NUMERIC(12, 6) NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_user_time_idx ON usage_ledger (user_id, created_at DESC);
