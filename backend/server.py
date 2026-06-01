#!/usr/bin/env python3
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBHOOK_PORT", "8099"))
TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
DB_NAME = os.environ.get("PAYMENT_DB", "payment_mvp")


def parse_payment(payload):
    text = " ".join(str(payload.get(k, "")) for k in ("title", "text", "sub_text"))
    amount = None
    amount_match = re.search(r"Rp\s*([0-9][0-9\.]*)", text, re.IGNORECASE)
    if amount_match:
        amount = int(amount_match.group(1).replace(".", ""))

    transaction_ref = None
    ref_match = re.search(r"ID\s*transaksi\s*[:#]?\s*([A-Za-z0-9._-]+)", text, re.IGNORECASE)
    if ref_match:
        transaction_ref = ref_match.group(1)
    return amount, transaction_ref


def psql_json(sql, params=None):
    env = os.environ.copy()
    env["PGDATABASE"] = DB_NAME
    cmd = ["psql", "-X", "-q", "-t", "-A", "-c", sql]
    if params:
        for key, value in params.items():
            cmd[1:1] = ["-v", f"{key}={value}"]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out.splitlines()[-1])


def sql_literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_json(value):
    return sql_literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def create_invoice(payload):
    external_id = payload.get("external_id")
    amount = payload.get("amount")
    customer_name = payload.get("customer_name")
    if not external_id or not isinstance(amount, int) or amount <= 0:
        raise ValueError("external_id and positive integer amount are required")
    sql = f"""
    INSERT INTO invoices (external_id, amount, customer_name)
    VALUES ({sql_literal(external_id)}, {amount}, {sql_literal(customer_name)})
    RETURNING row_to_json(invoices.*);
    """
    return psql_json(sql)


def list_invoices(limit):
    sql = f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM invoices ORDER BY id DESC LIMIT {limit}) t;"
    return psql_json(sql) or []


def list_events(limit):
    sql = f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM payment_events ORDER BY id DESC LIMIT {limit}) t;"
    return psql_json(sql) or []


def stats():
    sql = """
    SELECT json_build_object(
      'pending_invoices', (SELECT count(*) FROM invoices WHERE status='pending'),
      'paid_invoices', (SELECT count(*) FROM invoices WHERE status='paid'),
      'matched_events', (SELECT count(*) FROM payment_events WHERE status='matched'),
      'unmatched_events', (SELECT count(*) FROM payment_events WHERE status='unmatched')
    );
    """
    return psql_json(sql)


def store_event(payload, client_ip):
    amount, transaction_ref = parse_payment(payload)
    package_name = payload.get("package")
    title = payload.get("title")
    text = payload.get("text")
    sub_text = payload.get("sub_text")
    posted_at = payload.get("posted_at")

    if transaction_ref:
        exists = psql_json(f"SELECT row_to_json(t) FROM (SELECT id FROM payment_events WHERE transaction_ref={sql_literal(transaction_ref)} LIMIT 1) t;")
        if exists:
            status = "duplicate"
            invoice_id = None
        else:
            status, invoice_id = match_invoice(amount)
    else:
        status, invoice_id = match_invoice(amount)

    sql = f"""
    INSERT INTO payment_events (client_ip, package_name, title, text, sub_text, posted_at, raw_payload, parsed_amount, transaction_ref, status, invoice_id)
    VALUES ({sql_literal(client_ip)}::inet, {sql_literal(package_name)}, {sql_literal(title)}, {sql_literal(text)}, {sql_literal(sub_text)}, {sql_literal(posted_at)}::timestamptz, {sql_json(payload)}, {amount if amount else 'NULL'}, {sql_literal(transaction_ref)}, {sql_literal(status)}, {invoice_id if invoice_id else 'NULL'})
    RETURNING row_to_json(payment_events.*);
    """
    return psql_json(sql)


def match_invoice(amount):
    if not amount:
        return "unmatched", None
    invoice = psql_json(f"SELECT row_to_json(t) FROM (SELECT id FROM invoices WHERE status='pending' AND amount={amount} ORDER BY id ASC LIMIT 1) t;")
    if not invoice:
        return "unmatched", None
    invoice_id = invoice["id"]
    psql_json(f"UPDATE invoices SET status='paid', paid_at=now(), updated_at=now() WHERE id={invoice_id} RETURNING row_to_json(invoices.*);")
    return "matched", invoice_id


class Handler(BaseHTTPRequestHandler):
    server_version = "PaymentMVP/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(200, {"ok": True, "service": "payment-mvp"})
        elif parsed.path == "/api/stats":
            self.require_auth(lambda: self.send_json(200, stats()))
        elif parsed.path == "/api/invoices":
            self.require_auth(lambda: self.send_json(200, list_invoices(self.limit(parsed.query))))
        elif parsed.path == "/api/payment-events":
            self.require_auth(lambda: self.send_json(200, list_events(self.limit(parsed.query))))
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/webhook":
            self.require_auth(lambda: self.handle_webhook())
        elif parsed.path == "/api/invoices":
            self.require_auth(lambda: self.handle_create_invoice())
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})

    def require_auth(self, callback):
        if TOKEN and self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self.send_json(401, {"ok": False, "error": "unauthorized"})
            return
        callback()

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(min(length, 1024 * 1024))
        return json.loads(raw.decode("utf-8") or "{}")

    def handle_webhook(self):
        try:
            event = store_event(self.read_json(), self.client_address[0])
            self.send_json(200, {"ok": True, "event": event})
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)})

    def handle_create_invoice(self):
        try:
            invoice = create_invoice(self.read_json())
            self.send_json(201, {"ok": True, "invoice": invoice})
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)})

    def limit(self, query):
        try:
            return max(1, min(100, int(parse_qs(query).get("limit", [20])[0])))
        except Exception:
            return 20

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"Starting payment MVP on {HOST}:{PORT}, db={DB_NAME}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
