BEGIN;

CREATE TABLE IF NOT EXISTS merchants (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    callback_url TEXT,
    callback_secret TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id BIGSERIAL PRIMARY KEY,
    merchant_id BIGINT REFERENCES merchants(id),
    token TEXT NOT NULL UNIQUE,
    token_type TEXT NOT NULL CHECK (token_type IN ('admin', 'merchant', 'device')),
    name TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS devices (
    id BIGSERIAL PRIMARY KEY,
    merchant_id BIGINT NOT NULL REFERENCES merchants(id),
    name TEXT NOT NULL,
    package_filter TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'offline')),
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO merchants (name, slug)
VALUES ('Default Merchant', 'default')
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS merchant_id BIGINT REFERENCES merchants(id);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE payment_events ADD COLUMN IF NOT EXISTS merchant_id BIGINT REFERENCES merchants(id);
ALTER TABLE payment_events ADD COLUMN IF NOT EXISTS device_id BIGINT REFERENCES devices(id);
ALTER TABLE payment_events ADD COLUMN IF NOT EXISTS match_reason TEXT;

UPDATE invoices
SET merchant_id = (SELECT id FROM merchants WHERE slug='default')
WHERE merchant_id IS NULL;

UPDATE payment_events
SET merchant_id = (SELECT id FROM merchants WHERE slug='default')
WHERE merchant_id IS NULL;

ALTER TABLE invoices ALTER COLUMN merchant_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS invoices_merchant_status_amount_idx ON invoices(merchant_id, status, amount);
CREATE INDEX IF NOT EXISTS invoices_external_merchant_idx ON invoices(merchant_id, external_id);
CREATE INDEX IF NOT EXISTS payment_events_merchant_status_idx ON payment_events(merchant_id, status);
CREATE INDEX IF NOT EXISTS devices_merchant_idx ON devices(merchant_id);
CREATE INDEX IF NOT EXISTS api_tokens_token_idx ON api_tokens(token);

COMMIT;
