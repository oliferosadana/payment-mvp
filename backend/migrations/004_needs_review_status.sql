BEGIN;

ALTER TABLE payment_events DROP CONSTRAINT IF EXISTS payment_events_status_check;
ALTER TABLE payment_events ADD CONSTRAINT payment_events_status_check
    CHECK (status IN ('received', 'parsed', 'matched', 'unmatched', 'duplicate', 'needs_review'));

COMMIT;
