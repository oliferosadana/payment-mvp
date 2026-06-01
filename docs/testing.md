# Testing

## 1. Health Check

```bash
curl http://SERVER_IP:8099/health
```

Expected:

```json
{"ok": true, "service": "payment-mvp"}
```

## 2. Create Invoice

```bash
curl -H "Authorization: Bearer <WEBHOOK_TOKEN> \
  -H "Content-Type: application/json" \
  -X POST http://SERVER_IP:8099/api/invoices \
  -d '{"external_id":"INV-TEST-001","amount":1,"customer_name":"Test User"}'
```

Expected invoice status:

```text
pending
```

## 3. Simulate Payment Notification

```bash
curl -H "Authorization: Bearer <WEBHOOK_TOKEN> \
  -H "Content-Type: application/json" \
  -X POST http://SERVER_IP:8099/webhook \
  -d '{"package":"com.gojek.resto","title":"Pembayaran QRIS diterima!","text":"Rp1 berhasil diterima. ID transaksi: MVPTEST001","sub_text":"","posted_at":"2026-06-01T09:30:00.000Z"}'
```

Expected event:

```json
{
  "parsed_amount": 1,
  "transaction_ref": "MVPTEST001",
  "status": "matched"
}
```

## 4. Verify Invoice Paid

```bash
curl -H "Authorization: Bearer <WEBHOOK_TOKEN>" http://SERVER_IP:8099/api/invoices?limit=1
```

Expected invoice status:

```text
paid
```

## 5. Android End-to-End

1. Install APK.
2. Isi webhook URL dan token.
3. Isi package filter `com.gojek.resto`.
4. Aktifkan Notification Access.
5. Buat invoice dengan amount yang sama.
6. Trigger notifikasi payment nyata.
7. Cek `/api/payment-events` dan `/api/invoices`.

## SaaS v0.3 Checks

Cek invoice by external ID:

```bash
curl -H "Authorization: Bearer TOKEN" http://SERVER_IP:8099/api/invoices/by-external-id/SAAS-INV-001
```

Cek devices:

```bash
curl -H "Authorization: Bearer TOKEN" http://SERVER_IP:8099/api/devices
```

Cek dashboard sederhana:

```bash
curl -H "Authorization: Bearer TOKEN" http://SERVER_IP:8099/dashboard
```
