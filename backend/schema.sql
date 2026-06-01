CREATE TABLE IF NOT EXISTS invoices (
    id BIGSERIAL PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL CHECK (amount > 0),
    customer_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'expired', 'cancelled')),
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_events (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    client_ip INET,
    package_name TEXT,
    title TEXT,
    text TEXT,
    sub_text TEXT,
    posted_at TIMESTAMPTZ,
    raw_payload JSONB NOT NULL,
    parsed_amount INTEGER,
    transaction_ref TEXT,
    status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'parsed', 'matched', 'unmatched', 'duplicate')),
    invoice_id BIGINT REFERENCES invoices(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS payment_events_transaction_ref_unique
    ON payment_events(transaction_ref)
    WHERE transaction_ref IS NOT NULL AND transaction_ref <> '';

CREATE INDEX IF NOT EXISTS invoices_status_amount_idx ON invoices(status, amount);
CREATE INDEX IF NOT EXISTS payment_events_status_idx ON payment_events(status);
CREATE INDEX IF NOT EXISTS payment_events_received_at_idx ON payment_events(received_at DESC);
