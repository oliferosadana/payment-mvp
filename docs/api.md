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


## SaaS Endpoints v0.2

### POST /api/merchants

Admin only. Membuat merchant dan menghasilkan merchant token + device token.

Request:

```json
{
  "name": "Merchant A",
  "slug": "merchant-a"
}
```

Response:

```json
{
  "ok": true,
  "merchant": {"id": 2, "name": "Merchant A", "slug": "merchant-a"},
  "merchant_token": "pm_xxx",
  "device_token": "pm_yyy"
}
```

### GET /api/merchants

Admin only. List merchant.

### Token Roles

- `admin`: akses semua merchant dan membuat merchant.
- `merchant`: membuat invoice dan melihat invoice/event merchant sendiri.
- `device`: hanya untuk Android listener mengirim `/webhook`.

### POST /webhook v0.2

Gunakan device token. Optional field `device_name` akan dipakai untuk register/update device otomatis.

```json
{
  "device_name": "Device Kasir 1",
  "package": "com.gojek.resto",
  "title": "Pembayaran QRIS diterima!",
  "text": "Rp15.000 berhasil diterima. ID transaksi: ABC123",
  "sub_text": "",
  "posted_at": "2026-06-01T09:30:00.000Z"
}
```

## SaaS Endpoints v0.3

### GET /api/invoices/by-external-id/{external_id}

Mengambil detail invoice berdasarkan external ID. Merchant token hanya bisa melihat invoice miliknya sendiri.

### GET /api/devices

List device Android listener. Merchant token hanya melihat device miliknya sendiri.

### GET /dashboard

Dashboard HTML sederhana untuk cek endpoint dan role token aktif.

### Callback invoice.paid

Jika `merchants.callback_url` diisi, backend akan mengirim POST saat invoice berhasil matched dan berubah menjadi paid.

Payload callback:

```json
{
  "event": "invoice.paid",
  "merchant_id": 2,
  "invoice": {},
  "payment_event": {}
}
```

Jika `callback_secret` diisi, backend mengirim header:

```http
X-Callback-Secret: <callback_secret>
```
