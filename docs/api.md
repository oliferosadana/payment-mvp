# API Reference

Base URL contoh:

```text
http://192.168.18.102:8099
```

## Authentication

Semua endpoint selain `/health` membutuhkan header:

```http
Authorization: Bearer <WEBHOOK_TOKEN>
```

Token disimpan di server pada:

```text
/etc/default/notifier-webhook
```

## GET /health

Cek service aktif.

Response:

```json
{
  "ok": true,
  "service": "payment-mvp"
}
```

## POST /api/invoices

Membuat invoice baru.

Request:

```json
{
  "external_id": "INV-001",
  "amount": 15000,
  "customer_name": "Budi"
}
```

Response:

```json
{
  "ok": true,
  "invoice": {
    "id": 1,
    "external_id": "INV-001",
    "amount": 15000,
    "customer_name": "Budi",
    "status": "pending",
    "paid_at": null
  }
}
```

## GET /api/invoices

List invoice terbaru.

Query optional:

```text
?limit=20
```

## POST /webhook

Endpoint yang dipanggil Android listener.

Request:

```json
{
  "package": "com.gojek.resto",
  "title": "Pembayaran QRIS diterima!",
  "text": "Rp15.000 berhasil diterima. ID transaksi: ABC123",
  "sub_text": "",
  "posted_at": "2026-06-01T09:30:00.000Z"
}
```

Response jika matched:

```json
{
  "ok": true,
  "event": {
    "parsed_amount": 15000,
    "transaction_ref": "ABC123",
    "status": "matched",
    "invoice_id": 1
  }
}
```

Status event:

- `matched`: payment cocok dengan invoice pending
- `unmatched`: payment belum cocok dengan invoice
- `duplicate`: transaction ref sudah pernah diterima

## GET /api/payment-events

List payment event terbaru.

Query optional:

```text
?limit=20
```

## GET /api/stats

Ringkasan status MVP.

Response:

```json
{
  "pending_invoices": 0,
  "paid_invoices": 1,
  "matched_events": 1,
  "unmatched_events": 0
}
```
