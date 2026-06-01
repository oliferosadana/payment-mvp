#!/usr/bin/env python3
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBHOOK_PORT", "8099"))
ADMIN_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
DB_NAME = os.environ.get("PAYMENT_DB", "payment_mvp")
SESSIONS = {}


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


def session_context(cookie_header):
    for item in cookie_header.split(';'):
        name, _, value = item.strip().partition('=')
        if name == 'pm_session' and value in SESSIONS:
            return SESSIONS[value]
    return None

def create_session(ctx):
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = ctx
    return sid

def login_page(error=''):
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Login Payment SaaS</title><style>body{{font-family:Arial,sans-serif;background:#eef4ff;display:grid;place-items:center;min-height:100vh}}.box{{background:white;padding:28px;border-radius:20px;box-shadow:0 20px 50px #ccd6e6;max-width:420px;width:90%}}input,button{{width:100%;padding:12px;margin-top:10px;border-radius:12px;border:1px solid #d1d5db}}button{{background:#2563eb;color:white;border:0}}</style></head><body><form class='box' method='post' action='/dashboard/login'><h1>Payment SaaS</h1><p>Login memakai admin token atau merchant token.</p><p style='color:#b91c1c'>{error}</p><input name='token' type='password' placeholder='Token'><button>Login</button></form></body></html>"""

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


def list_tokens(ctx):
    require_type(ctx, {"admin"})
    return psql_json("SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT t.id, t.merchant_id, m.name AS merchant_name, t.token_type, t.name, t.token, t.status, t.last_used_at, t.created_at FROM api_tokens t JOIN merchants m ON m.id=t.merchant_id ORDER BY t.id DESC LIMIT 200) t;") or []


def regenerate_token(ctx, payload):
    require_type(ctx, {"admin"})
    token_id = payload.get("token_id")
    if not isinstance(token_id, int):
        raise ValueError("token_id is required integer")
    token = create_token()
    return psql_json(f"UPDATE api_tokens SET token={sql_literal(token)}, status='active' WHERE id={token_id} RETURNING row_to_json(api_tokens.*);")


def set_token_status(ctx, payload):
    require_type(ctx, {"admin"})
    token_id = payload.get("token_id")
    status = payload.get("status")
    if not isinstance(token_id, int) or status not in {"active", "disabled"}:
        raise ValueError("token_id and status active/disabled are required")
    return psql_json(f"UPDATE api_tokens SET status={sql_literal(status)} WHERE id={token_id} RETURNING row_to_json(api_tokens.*);")


def cancel_invoice(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    invoice_id = payload.get("invoice_id")
    if not isinstance(invoice_id, int):
        raise ValueError("invoice_id is required integer")
    scope = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"UPDATE invoices SET status='cancelled', updated_at=now() WHERE id={invoice_id} AND {scope} AND status='pending' RETURNING row_to_json(invoices.*);")


def update_device(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    device_id = payload.get("device_id")
    package_filter = payload.get("package_filter")
    status = payload.get("status") or "active"
    if not isinstance(device_id, int) or status not in {"active", "disabled"}:
        raise ValueError("device_id and status active/disabled are required")
    scope = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"UPDATE devices SET package_filter={sql_literal(package_filter)}, status={sql_literal(status)}, updated_at=now() WHERE id={device_id} AND {scope} RETURNING row_to_json(devices.*);")


def defang_tokens(rows):
    for row in rows:
        token = row.get("token") or ""
        row["token_preview"] = token[:8] + "..." + token[-6:] if len(token) > 16 else token
    return rows


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
    return psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT *, CASE WHEN last_seen_at > now() - interval '5 minutes' THEN 'online' ELSE 'offline' END AS online_status FROM devices WHERE {where} ORDER BY id DESC LIMIT {limit}) t;") or []


def manual_match_event(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    event_id = payload.get("event_id")
    invoice_id = payload.get("invoice_id")
    if not isinstance(event_id, int) or not isinstance(invoice_id, int):
        raise ValueError("event_id and invoice_id are required integers")
    scope = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    event = psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM payment_events WHERE id={event_id} AND {scope} LIMIT 1) t;")
    invoice = psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM invoices WHERE id={invoice_id} AND {scope} AND status='pending' LIMIT 1) t;")
    if not event or not invoice:
        raise ValueError("event or pending invoice not found in scope")
    psql_json(f"UPDATE invoices SET status='paid', paid_at=now(), updated_at=now() WHERE id={invoice_id} RETURNING row_to_json(invoices.*);")
    updated = psql_json(f"UPDATE payment_events SET status='matched', invoice_id={invoice_id}, match_reason='manual_review_match' WHERE id={event_id} RETURNING row_to_json(payment_events.*);")
    updated["callback"] = send_callback(updated["merchant_id"], invoice_id, updated)
    return updated


def list_callback_attempts(ctx, limit):
    require_type(ctx, {"admin", "merchant"})
    where = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    return psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM callback_attempts WHERE {where} ORDER BY id DESC LIMIT {limit}) t;") or []


def retry_callback(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, int):
        raise ValueError("attempt_id is required integer")
    scope = "TRUE" if ctx["token_type"] == "admin" else f"merchant_id={ctx['merchant_id']}"
    attempt = psql_json(f"SELECT row_to_json(t) FROM (SELECT * FROM callback_attempts WHERE id={attempt_id} AND {scope} LIMIT 1) t;")
    if not attempt:
        raise ValueError("callback attempt not found")
    return send_callback(attempt["merchant_id"], attempt["invoice_id"], {"id": attempt["payment_event_id"]})


def update_merchant_callback(ctx, payload):
    require_type(ctx, {"admin", "merchant"})
    merchant_id = payload.get("merchant_id") if ctx["token_type"] == "admin" else ctx["merchant_id"]
    callback_url = payload.get("callback_url")
    callback_secret = payload.get("callback_secret")
    return psql_json(f"UPDATE merchants SET callback_url={sql_literal(callback_url)}, callback_secret={sql_literal(callback_secret)}, updated_at=now() WHERE id={merchant_id} RETURNING row_to_json(merchants.*);")

def retry_failed_callbacks_once(limit=10):
    rows = psql_json(f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM callback_attempts WHERE status='failed' ORDER BY id ASC LIMIT {limit}) t;") or []
    for row in rows:
        send_callback(row["merchant_id"], row["invoice_id"], {"id": row["payment_event_id"]})

def retry_worker():
    while True:
        try:
            retry_failed_callbacks_once()
        except Exception as exc:
            print(f"callback retry worker error: {exc}", flush=True)
        time.sleep(60)

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
    status, http_status, error = "pending", None, None
    req = urllib.request.Request(merchant["callback_url"], data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if merchant.get("callback_secret"):
        req.add_header("X-Callback-Secret", merchant["callback_secret"])
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            http_status = resp.status
            status = "success" if 200 <= resp.status <= 299 else "failed"
    except Exception as exc:
        status = "failed"
        error = exc.__class__.__name__
    attempt = psql_json(f"""
        INSERT INTO callback_attempts (merchant_id, invoice_id, payment_event_id, callback_url, payload, status, http_status, error)
        VALUES ({merchant_id}, {invoice_id if invoice_id else 'NULL'}, {sql_literal(event.get('id'))}, {sql_literal(merchant['callback_url'])}, {sql_json(payload)}, {sql_literal(status)}, {http_status if http_status else 'NULL'}, {sql_literal(error)})
        RETURNING row_to_json(callback_attempts.*);
    """)
    return {"sent": status == "success", "status": http_status, "error": error, "attempt_id": attempt["id"]}


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
    role = ctx["token_type"]
    merchant_id = ctx.get("merchant_id")
    admin_tools = "" if role != "admin" else """
<section class="panel admin-only">
  <div class="panel-head"><div><p class="eyebrow">Admin</p><h2>Merchant & Token Management</h2></div></div>
  <div class="form-grid compact"><input id="mname" placeholder="Merchant name"><input id="mslug" placeholder="merchant-slug"><button onclick="createMerchant()">Create Merchant</button></div>
  <pre id="merchantResult" class="result"></pre>
  <div class="split"><div><h3>Merchants</h3><div id="merchants"></div></div><div><h3>API Tokens</h3><div id="tokens"></div></div></div>
</section>"""
    html = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment SaaS Dashboard</title><style>
:root{--ink:#172019;--muted:#68746c;--paper:#fffaf0;--card:#fffdf7;--line:#e6dcc8;--green:#1f7a4d;--red:#b33939;--amber:#a06100;--blue:#225c7a;--shadow:0 18px 50px rgba(57,43,22,.12)}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 8% 0%,#ffe6a3 0,transparent 30%),linear-gradient(135deg,#f5efe1,#e8f0df 55%,#f8e7d4);color:var(--ink);font-family:Georgia,'Times New Roman',serif}.wrap{max-width:1320px;margin:0 auto;padding:28px}.hero{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:22px}.brand{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}h1{font-size:42px;line-height:1;margin:8px 0}h2{margin:0;font-size:24px}h3{margin:18px 0 10px}.pill{display:inline-flex;gap:8px;align-items:center;background:#1d2b22;color:#fff;padding:9px 13px;border-radius:999px;font-family:ui-monospace,monospace;font-size:13px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.panel{grid-column:span 12;background:rgba(255,253,247,.9);border:1px solid var(--line);border-radius:24px;padding:20px;box-shadow:var(--shadow);backdrop-filter:blur(10px)}.half{grid-column:span 6}.third{grid-column:span 4}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-bottom:14px}.eyebrow{margin:0 0 4px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.14em}.form-grid{display:grid;grid-template-columns:1.3fr .8fr 1fr auto;gap:10px}.compact{grid-template-columns:1fr 1fr auto}.split{display:grid;grid-template-columns:1fr 1.3fr;gap:18px}input{width:100%;border:1px solid var(--line);background:#fff;border-radius:14px;padding:12px 13px;font:16px Georgia,'Times New Roman',serif}button{border:0;border-radius:14px;background:#1d2b22;color:#fff;padding:12px 15px;cursor:pointer;font-weight:700}button.secondary{background:#e9ddc7;color:#1d2b22}.result{white-space:pre-wrap;max-height:180px;overflow:auto;background:#1d2b22;color:#dff4df;border-radius:16px;padding:12px;display:none}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.stat{background:#f7eddb;border:1px solid var(--line);border-radius:18px;padding:14px}.stat b{display:block;font-size:30px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:18px;background:#fff}table{width:100%;border-collapse:collapse;font-size:14px;font-family:ui-sans-serif,system-ui,sans-serif}th{position:sticky;top:0;background:#f4ead8;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b5d4a}td,th{padding:10px;border-bottom:1px solid #eee4d1;vertical-align:top}td{max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.status{font-weight:800}.paid,.matched,.success,.active,.online{color:var(--green)}.pending,.needs_review{color:var(--amber)}.failed,.unmatched,.disabled,.offline,.cancelled{color:var(--red)}.empty{padding:18px;color:var(--muted);background:#fff;border-radius:18px;border:1px dashed var(--line)}.actions{white-space:normal;min-width:170px}.actions button{padding:8px 10px;margin:2px;font-size:12px}.toast{position:fixed;right:22px;bottom:22px;background:#1d2b22;color:#fff;padding:14px 16px;border-radius:16px;box-shadow:var(--shadow);display:none}@media(max-width:900px){.hero,.split{display:block}.half,.third{grid-column:span 12}.form-grid,.compact,.stats{grid-template-columns:1fr}h1{font-size:32px}.wrap{padding:16px}}</style></head><body><div class="wrap"><header class="hero"><div><p class="brand">Payment SaaS</p><h1>Merchant Operations</h1><span class="pill">Role: ROLE | Merchant: MERCHANT</span></div><button class="secondary" onclick="logout()">Logout</button></header><main class="grid"><section class="panel"><div class="panel-head"><div><p class="eyebrow">Overview</p><h2>Realtime Stats</h2></div><button class="secondary" onclick="load()">Refresh</button></div><div id="stats" class="stats"></div></section><section class="panel half"><p class="eyebrow">Invoice</p><h2>Create Invoice</h2><div class="form-grid"><input id="external_id" placeholder="External ID"><input id="amount" type="number" placeholder="Amount"><input id="customer_name" placeholder="Customer name"><button onclick="createInvoice()">Create</button></div><pre id="invoiceResult" class="result"></pre></section><section class="panel half"><p class="eyebrow">Integration</p><h2>Callback Setting</h2><div class="form-grid compact"><input id="callback_url" placeholder="https://merchant.app/callback"><input id="callback_secret" placeholder="Callback secret"><button onclick="saveCallback()">Save</button></div><pre id="callbackResult" class="result"></pre></section>ADMIN_TOOLS<section class="panel"><div class="panel-head"><div><p class="eyebrow">Invoices</p><h2>Recent Invoices</h2></div></div><div id="invoices"></div></section><section class="panel"><p class="eyebrow">Payments</p><h2>Payment Events</h2><div id="events"></div></section><section class="panel half"><p class="eyebrow">Android</p><h2>Devices</h2><div id="devices"></div></section><section class="panel half"><p class="eyebrow">Webhook</p><h2>Callback Attempts</h2><div id="callbacks"></div></section></main></div><div id="toast" class="toast"></div><script>
function h(){return {'Content-Type':'application/json'}}
function toast(msg){toastEl=document.getElementById('toast');toastEl.textContent=msg;toastEl.style.display='block';setTimeout(()=>toastEl.style.display='none',2600)}
async function api(p,o={}){let r=await fetch(p,{...o,headers:h()});if(r.status===401) location='/dashboard/login';let d=await r.json();if(!r.ok||d.ok===false) throw new Error(d.detail||d.error||'request failed');return d}
function esc(v){return String(v==null?'':v).replace(/[&<>\"]/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s]))}
function cell(v){if(typeof v==='string'&&v.startsWith('<button'))return v;if(typeof v==='object'&&v!==null)v=JSON.stringify(v);return esc(v)}
function table(rows){if(!rows||!rows.length)return '<div class="empty">No data yet</div>';let cols=Object.keys(rows[0]);return '<div class="table-wrap"><table><tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+cols.map(c=>'<td class="'+esc(String(r[c]))+' '+(c==='action'?'actions':'')+'">'+cell(r[c])+'</td>').join('')+'</tr>').join('')+'</table></div>'}
function showResult(id,data){let el=document.getElementById(id);el.style.display='block';el.textContent=JSON.stringify(data,null,2)}
async function createInvoice(){try{let body={external_id:external_id.value,amount:+amount.value,customer_name:customer_name.value};showResult('invoiceResult',await api('/api/invoices',{method:'POST',body:JSON.stringify(body)}));toast('Invoice created');load()}catch(e){toast(e.message)}}
async function createMerchant(){try{let body={name:mname.value,slug:mslug.value};showResult('merchantResult',await api('/api/merchants',{method:'POST',body:JSON.stringify(body)}));toast('Merchant created');load()}catch(e){toast(e.message)}}
async function saveCallback(){try{showResult('callbackResult',await api('/api/merchants/callback',{method:'POST',body:JSON.stringify({callback_url:callback_url.value,callback_secret:callback_secret.value})}));toast('Callback saved')}catch(e){toast(e.message)}}
async function manual(eventId){let invoiceId=prompt('Invoice ID untuk match manual?');if(!invoiceId)return;try{await api('/api/payment-events/manual-match',{method:'POST',body:JSON.stringify({event_id:+eventId,invoice_id:+invoiceId})});toast('Matched');load()}catch(e){toast(e.message)}}
async function retry(id){try{await api('/api/callback-attempts/retry',{method:'POST',body:JSON.stringify({attempt_id:+id})});toast('Retry sent');load()}catch(e){toast(e.message)}}
async function cancelInv(id){if(!confirm('Cancel invoice '+id+'?'))return;try{await api('/api/invoices/cancel',{method:'POST',body:JSON.stringify({invoice_id:+id})});toast('Invoice cancelled');load()}catch(e){toast(e.message)}}
async function regenToken(id){if(!confirm('Regenerate token '+id+'?'))return;try{await api('/api/tokens/regenerate',{method:'POST',body:JSON.stringify({token_id:+id})});toast('Token regenerated');load()}catch(e){toast(e.message)}}
async function tokenStatus(id,status){try{await api('/api/tokens/status',{method:'POST',body:JSON.stringify({token_id:+id,status})});toast('Token updated');load()}catch(e){toast(e.message)}}
async function updateDevice(id){let pf=prompt('Package filter?');if(pf===null)return;try{await api('/api/devices/update',{method:'POST',body:JSON.stringify({device_id:+id,package_filter:pf,status:'active'})});toast('Device updated');load()}catch(e){toast(e.message)}}
async function logout(){await fetch('/dashboard/logout',{method:'POST'});location='/dashboard/login'}
function statCards(s){return ['pending_invoices','paid_invoices','matched_events','unmatched_events','needs_review_events'].map(k=>'<div class="stat"><span>'+k.replaceAll('_',' ')+'</span><b>'+esc(s[k]||0)+'</b></div>').join('')}
async function load(){try{document.getElementById('stats').innerHTML=statCards(await api('/api/stats'));let inv=await api('/api/invoices?limit=20');invoices.innerHTML=table(inv.map(i=>({...i,status:'<span class="status '+i.status+'">'+i.status+'</span>',action:i.status==='pending'?'<button onclick="cancelInv('+i.id+')">cancel</button>':''})));let ev=await api('/api/payment-events?limit=20');events.innerHTML=table(ev.map(e=>({...e,status:'<span class="status '+e.status+'">'+e.status+'</span>',action:e.status==='needs_review'?'<button onclick="manual('+e.id+')">match</button>':''})));devices.innerHTML=table((await api('/api/devices?limit=20')).map(d=>({...d,action:'<button onclick="updateDevice('+d.id+')">edit</button>'})));callbacks.innerHTML=table((await api('/api/callback-attempts?limit=20')).map(c=>({...c,status:'<span class="status '+c.status+'">'+c.status+'</span>',action:c.status==='failed'?'<button onclick="retry('+c.id+')">retry</button>':''})));if(document.getElementById('merchants')){merchants.innerHTML=table(await api('/api/merchants'));tokens.innerHTML=table((await api('/api/tokens')).map(t=>({...t,token:t.token_preview,action:'<button onclick="regenToken('+t.id+')">regen</button><button onclick="tokenStatus('+t.id+',&quot;disabled&quot;)">disable</button><button onclick="tokenStatus('+t.id+',&quot;active&quot;)">enable</button>'})))}}catch(e){toast(e.message)}}
load();</script></body></html>"""
    return html.replace("ROLE", role).replace("MERCHANT", str(merchant_id)).replace("ADMIN_TOOLS", admin_tools)


class Handler(BaseHTTPRequestHandler):
    server_version = "PaymentSaaS/0.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(200, {"ok": True, "service": "payment-saas", "version": "0.4"})
            return
        if parsed.path == "/dashboard/login":
            self.send_html(200, login_page())
            return
        if parsed.path == "/dashboard" and not session_context(self.headers.get("Cookie", "")):
            self.redirect("/dashboard/login")
            return
        self.with_auth(lambda ctx: self.route_get(ctx, parsed))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/dashboard/login":
            data = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            ctx = auth_context("Bearer " + data.get("token", [""])[0])
            if not ctx or ctx.get("token_type") not in {"admin", "merchant"}:
                self.send_html(401, login_page("Token tidak valid"))
                return
            sid = create_session(ctx)
            self.send_response(302)
            self.send_header("Set-Cookie", f"pm_session={sid}; HttpOnly; SameSite=Lax; Path=/")
            self.send_header("Location", "/dashboard")
            self.end_headers()
            return
        if parsed.path == "/dashboard/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "pm_session=; Max-Age=0; Path=/")
            self.send_header("Location", "/dashboard/login")
            self.end_headers()
            return
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
        elif parsed.path == "/api/callback-attempts":
            self.send_json(200, list_callback_attempts(ctx, self.limit(parsed.query)))
        elif parsed.path == "/api/merchants":
            require_type(ctx, {"admin"})
            self.send_json(200, list_merchants())
        elif parsed.path == "/api/tokens":
            self.send_json(200, defang_tokens(list_tokens(ctx)))
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
        elif parsed.path == "/api/payment-events/manual-match":
            self.send_json(200, {"ok": True, "event": manual_match_event(ctx, self.read_json())})
        elif parsed.path == "/api/callback-attempts/retry":
            self.send_json(200, {"ok": True, "callback": retry_callback(ctx, self.read_json())})
        elif parsed.path == "/api/merchants/callback":
            self.send_json(200, {"ok": True, "merchant": update_merchant_callback(ctx, self.read_json())})
        elif parsed.path == "/api/tokens/regenerate":
            self.send_json(200, {"ok": True, "token": regenerate_token(ctx, self.read_json())})
        elif parsed.path == "/api/tokens/status":
            self.send_json(200, {"ok": True, "token": set_token_status(ctx, self.read_json())})
        elif parsed.path == "/api/invoices/cancel":
            self.send_json(200, {"ok": True, "invoice": cancel_invoice(ctx, self.read_json())})
        elif parsed.path == "/api/devices/update":
            self.send_json(200, {"ok": True, "device": update_device(ctx, self.read_json())})
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})

    def with_auth(self, callback):
        try:
            ctx = auth_context(self.headers.get("Authorization", "")) or session_context(self.headers.get("Cookie", ""))
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

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

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
    threading.Thread(target=retry_worker, daemon=True).start()
    print(f"Starting payment SaaS on {HOST}:{PORT}, db={DB_NAME}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
