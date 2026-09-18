CREATE TABLE IF NOT EXISTS edge_devices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    cliente_id TEXT NOT NULL,
    unidade_id TEXT NOT NULL,
    nome TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS edge_events (
    id TEXT PRIMARY KEY,
    event_uuid TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    cliente_id TEXT NOT NULL,
    unidade_id TEXT NOT NULL,
    edge_id TEXT NOT NULL REFERENCES edge_devices(id),
    camera_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    inicio TIMESTAMPTZ,
    fim TIMESTAMPTZ,
    duracao DOUBLE PRECISION,
    operador_presente BOOLEAN,
    confianca DOUBLE PRECISION,
    severidade TEXT,
    status TEXT,
    midia_path TEXT,
    payload_json TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edge_events_tenant_received
    ON edge_events (tenant_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_edge_events_edge_received
    ON edge_events (edge_id, received_at DESC);
