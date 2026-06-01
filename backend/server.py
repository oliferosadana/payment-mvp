#!/usr/bin/env python3
import json
import os
import re
import secrets
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBHOOK_PORT", "8099"))
ADMIN_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
DB_NAME = os.environ.get("PAYMENT_DB", "payment_mvp")


def sql_literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_json(value):
    return sql_literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def psql_json(sql):
    env = os.environ.copy()
    env["PGDATABASE"] = DB_NAME
    result = subprocess.run(["psql", "-X", "-q", "-t", "-A", "-c", sql], text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out.splitlines()[-1])


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


def auth_context(header):
    prefix = "Bearer "
    if not header.startswith(prefix):
        return None
    token = header[len(prefix):].strip()
    if ADMIN_TOKEN and token == ADMIN_TOKEN:
        return {"token_type": "admin", "merchant_id": None, "token": token}
    row = psql_json(f"SELECT row_to_json(t) FROM (SELECT id, merchant_id, token_type, name FROM api_tokens WHERE token={sql_literal(token)} AND status='active' LIMIT 1) t;")
    if row:
        psql_json(f"UPDATE api_tokens SET last_used_at=now() WHERE id={row['id']} RETURNING row_to_json(api_tokens.*);")
        row["token"] = token
        return row
    return None


def require_type(ctx, allowed):
    if not ctx or ctx.get("token_type") not in allowed:
        raise PermissionError("forbidden")


def create_token():
    return "pm_" + secrets.token_urlsafe(32)


def create_merchant(payload):
    name = payload.get("name")
    slug = payload.get("slug")
    callback_url = payload.get("callback_url")
    if not name or not slug:
        raise ValueError("name and slug are required")
    merchant = psql_json(f"""
        INSERT INTO merchants (name, slug, callback_url)
        VALUES ({sql_literal(name)}, {sql_literal(slug)}, {sql_literal(callback_url)})
        RETURNING row_to_json(merchants.*);
    """)
    merchant_token = create_token()
    device_token = create_token()
    merchant_api = psql_json(f"""
        INSERT INTO api_tokens (merchant_id, token, token_type, name)
        VALUES ({merchant['id']}, {sql_literal(merchant_token)}, 'merchant', 'Merchant API')
        RETURNING row_to_json(api_tokens.*);
    """)
    device_api = psql_json(f"""
        INSERT INTO api_tokens (merchant_id, token, token_type, name)
        VALUES ({merchant['id']}, {sql_literal(device_token)}, 'device', 'Default Device Token')
        RETURNING row_to_json(api_tokens.*);
    """)
    return {"merchant": merchant, "merchant_token": merchant_api["token"], "device_token": device_api["token"]}


def list_merchants():
    return psql_json("SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT id, name, slug, status, created_at FROM merchants ORDER BY id DESC LIMIT 100) t;") or []


def ensure_device(ctx, payload):
    device_name = payload.get("device_name") or ctx.get("name") or "Android Listener"
    device = psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM devices WHERE merchant_id={ctx['merchant_id']} AND name={sql_literal(device_name)} LIMIT 1) t;")
    if device:
        psql_json(f"UPDATE devices SET last_seen_at=now(), status='active', updated_at=now() WHERE id={device['id']} RETURNING row_to_json(devices.*);")
        return device
    return psql_json(f"""
        INSERT INTO devices (merchant_id, name, last_seen_at)
        VALUES ({ctx['merchant_id']}, {sql_literal(device_name)}, now())
        RETURNING row_to_json(devices.*);
    """)


def create_invoice(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    merchant_id = payload.get("merchant_id") if ctx["token_type"] == "admin" else ctx["merchant_id"]
    external_id = payload.get("external_id")
    amount = payload.get("amount")
    customer_name = payload.get("customer_name")
    expires_at = payload.get("expires_at")
    metadata = payload.get("metadata") or {}
    if not merchant_id or not external_id or not isinstance(amount, int) or amount <= 0:
        raise ValueError("merchant_id/admin or merchant token, external_id, and positive integer amount are required")
    return psql_json(f"""
        INSERT INTO invoices (merchant_id, external_id, amount, customer_name, expires_at, metadata)
        VALUES ({merchant_id}, {sql_literal(external_id)}, {amount}, {sql_literal(customer_name)}, {sql_literal(expires_at)}::timestamptz, {sql_json(metadata)})
        RETURNING row_to_json(invoices.*);
    """)


def list_invoices(ctx, limit):
    where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM invoices WHERE {where} ORDER BY id DESC LIMIT {limit}) t;") or []


def get_invoice_by_external_id(ctx, external_id):
    where = f"external_id={sql_literal(external_id)}"
    if ctx["token_type"] != "admin":
        where += f" AND merchant_id={ctx['merchant_id']}"
    return psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM invoices WHERE {where} LIMIT 1) t;")


def list_devices(ctx, limit):
    require_type(ctx, {"admin", "merchant"})
    where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM devices WHERE {where} ORDER BY id DESC LIMIT {limit}) t;") or []


def list_events(ctx, limit):
    where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM payment_events WHERE {where} ORDER BY id DESC LIMIT {limit}) t;") or []


def stats(ctx):
    inv_where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    ev_where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"""
        SELECT json_build_object(
          'pending_invoices', (SELECT count(*) FROM invoices WHERE {inv_where} AND status='pending'),
          'paid_invoices', (SELECT count(*) FROM invoices WHERE {inv_where} AND status='paid'),
          'matched_events', (SELECT count(*) FROM payment_events WHERE {ev_where} AND status='matched'),
          'unmatched_events', (SELECT count(*) FROM payment_events WHERE {ev_where} AND status='unmatched'),
          'needs_review_events', (SELECT count(*) FROM payment_events WHERE {ev_where} AND status='needs_review')
        );
    """)


def match_invoice(merchant_id, amount):
    if not amount:
        return "unmatched", None, "amount_not_found"
    candidates = psql_json(f"""
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
        FROM (
            SELECT id FROM invoices
            WHERE merchant_id={merchant_id}
              AND status='pending'
              AND amount={amount}
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY id ASC
            LIMIT 2
        ) t;
    """) or []
    if len(candidates) == 0:
        return "unmatched", None, "no_pending_invoice_for_amount"
    if len(candidates) > 1:
        return "needs_review", None, "multiple_pending_invoices_for_amount"
    invoice_id = candidates[0]["id"]
    psql_json(f"UPDATE invoices SET status='paid', paid_at=now(), updated_at=now() WHERE id={invoice_id} RETURNING row_to_json(invoices.*);")
    return "matched", invoice_id, "single_pending_invoice_amount_match"


def merchant_for_callback(merchant_id):
    return psql_json(f"SELECT row_to_json(t) FROM (SELECT id, name, slug, callback_url, callback_secret FROM merchants WHERE id={merchant_id} LIMIT 1) t;")


def invoice_by_id(invoice_id):
    return psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM invoices WHERE id={invoice_id} LIMIT 1) t;")


def send_callback(merchant_id, invoice_id, event):
    merchant = merchant_for_callback(merchant_id)
    if not merchant or not merchant.get("callback_url"):
        return {"sent": False, "reason": "callback_url_empty"}
    invoice = invoice_by_id(invoice_id)
    payload = {"event": "invoice.paid", "merchant_id": merchant_id, "invoice": invoice, "payment_event": event}
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(merchant["callback_url"], data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if merchant.get("callback_secret"):
        req.add_header("X-Callback-Secret", merchant["callback_secret"])
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"sent": True, "status": resp.status}
    except Exception as exc:
        return {"sent": False, "reason": exc.__class__.__name__}


def store_event(ctx, payload, client_ip):
    require_type(ctx, {"device"})
    device = ensure_device(ctx, payload)
    amount, transaction_ref = parse_payment(payload)
    if transaction_ref:
        exists = psql_json(f"SELECT row_to_json(t) FROM (SELECT id FROM payment_events WHERE transaction_ref={sql_literal(transaction_ref)} LIMIT 1) t;")
        if exists:
            status, invoice_id, reason = "duplicate", None, "duplicate_transaction_ref"
        else:
            status, invoice_id, reason = match_invoice(ctx["merchant_id"], amount)
    else:
        status, invoice_id, reason = match_invoice(ctx["merchant_id"], amount)
    event = psql_json(f"""
        INSERT INTO payment_events (merchant_id, device_id, client_ip, package_name, title, text, sub_text, posted_at, raw_payload, parsed_amount, transaction_ref, status, invoice_id, match_reason)
        VALUES ({ctx['merchant_id']}, {device['id']}, {sql_literal(client_ip)}::inet, {sql_literal(payload.get('package'))}, {sql_literal(payload.get('title'))}, {sql_literal(payload.get('text'))}, {sql_literal(payload.get('sub_text'))}, {sql_literal(payload.get('posted_at'))}::timestamptz, {sql_json(payload)}, {amount if amount else 'NULL'}, {sql_literal(transaction_ref)}, {sql_literal(status)}, {invoice_id if invoice_id else 'NULL'}, {sql_literal(reason)})
        RETURNING row_to_json(payment_events.*);
    """)
    if status == "matched" and invoice_id:
        event["callback"] = send_callback(ctx["merchant_id"], invoice_id, event)
    return event


def dashboard_html(ctx):
    merchant_filter = "" if ctx["token_type"] == "admin" else f"&merchant={ctx['merchant_id']}"
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Payment SaaS</title><style>body{{font-family:Arial,sans-serif;background:#f4f7fb;margin:0;padding:24px;color:#111827}}.card{{background:white;border-radius:18px;padding:20px;margin:0 auto 18px;max-width:980px;box-shadow:0 10px 30px #d7dee8}}h1{{margin:0 0 8px}}code{{background:#eef2ff;padding:2px 6px;border-radius:6px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left}}.paid{{color:#15803d}}.pending{{color:#b45309}}</style></head><body><div class='card'><h1>Payment SaaS Dashboard</h1><p>Gunakan API untuk data live. Endpoint cepat: <code>/api/stats</code>, <code>/api/invoices</code>, <code>/api/payment-events</code>, <code>/api/devices</code>.</p><p>Role token aktif: <code>{ctx['token_type']}</code>{merchant_filter}</p></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PaymentSaaS/0.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(200, {"ok": True, "service": "payment-saas", "version": "0.2"})
            return
        self.with_auth(lambda ctx: self.route_get(ctx, parsed))

    def do_POST(self):
        parsed = urlparse(self.path)
        self.with_auth(lambda ctx: self.route_post(ctx, parsed))

    def route_get(self, ctx, parsed):
        if parsed.path == "/dashboard":
            self.send_html(200, dashboard_html(ctx))
        elif parsed.path == "/api/stats":
            self.send_json(200, stats(ctx))
        elif parsed.path == "/api/invoices":
            self.send_json(200, list_invoices(ctx, self.limit(parsed.query)))
        elif parsed.path.startswith("/api/invoices/by-external-id/"):
            external_id = parsed.path.rsplit("/", 1)[-1]
            invoice = get_invoice_by_external_id(ctx, external_id)
            self.send_json(200 if invoice else 404, {"ok": bool(invoice), "invoice": invoice})
        elif parsed.path == "/api/payment-events":
            self.send_json(200, list_events(ctx, self.limit(parsed.query)))
        elif parsed.path == "/api/devices":
            self.send_json(200, list_devices(ctx, self.limit(parsed.query)))
        elif parsed.path == "/api/merchants":
            require_type(ctx, {"admin"})
            self.send_json(200, list_merchants())
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})

    def route_post(self, ctx, parsed):
        if parsed.path == "/webhook":
            self.send_json(200, {"ok": True, "event": store_event(ctx, self.read_json(), self.client_address[0])})
        elif parsed.path == "/api/invoices":
            self.send_json(201, {"ok": True, "invoice": create_invoice(ctx, self.read_json())})
        elif parsed.path == "/api/merchants":
            require_type(ctx, {"admin"})
            self.send_json(201, {"ok": True, **create_merchant(self.read_json())})
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})

    def with_auth(self, callback):
        try:
            ctx = auth_context(self.headers.get("Authorization", ""))
            if not ctx:
                self.send_json(401, {"ok": False, "error": "unauthorized"})
                return
            callback(ctx)
        except PermissionError as exc:
            self.send_json(403, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)})

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(min(length, 1024 * 1024))
        return json.loads(raw.decode("utf-8") or "{}")

    def limit(self, query):
        try:
            return max(1, min(100, int(parse_qs(query).get("limit", [20])[0])))
        except Exception:
            return 20

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_html(self, status, html):
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"Starting payment SaaS on {HOST}:{PORT}, db={DB_NAME}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
