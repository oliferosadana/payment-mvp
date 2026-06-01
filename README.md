# Payment MVP

Payment MVP adalah eksperimen payment detection berbasis notifikasi Android. Aplikasi Android menangkap notifikasi dari aplikasi payment tertentu, mengirim payload ke backend webhook, lalu backend mem-parse nominal dan ID transaksi untuk mencocokkan invoice pending.

> Catatan: proyek ini cocok untuk MVP/internal automation. Untuk production payment gateway, tetap butuh validasi resmi dari penyedia pembayaran, monitoring, audit, dan kontrol risiko yang lebih kuat.

## Komponen

```text
payment-mvp/
  android-listener/   Android Notification Listener app
  backend/            Python webhook receiver + Payment SaaS API
  docs/               Dokumentasi arsitektur, API, deployment, dan testing
```

## Flow Sistem

```text
Android Notification Listener
  -> POST /webhook
  -> Backend parse amount + transaction_ref
  -> Store payment_events per merchant/device
  -> Match pending invoice by merchant + amount
  -> Mark invoice as paid
```

## Endpoint Utama

- `GET /health`
- `POST /webhook`
- `POST /api/invoices`
- `GET /api/invoices`
- `GET /api/payment-events`
- `GET /api/stats`
- `POST /api/merchants` admin only
- `GET /api/merchants` admin only

Semua endpoint selain `/health` memakai header token bearer.

## Quick Test

Buat invoice:

```bash
curl -H "Authorization: Bearer TOKEN_ANDA" \
  -H "Content-Type: application/json" \
  -X POST http://SERVER_IP:8099/api/invoices \
  -d '{"external_id":"INV-001","amount":15000,"customer_name":"Budi"}'
```

Simulasi notifikasi payment:

```bash
curl -H "Authorization: Bearer TOKEN_ANDA" \
  -H "Content-Type: application/json" \
  -X POST http://SERVER_IP:8099/webhook \
  -d '{"package":"com.gojek.resto","title":"Pembayaran QRIS diterima!","text":"Rp15.000 berhasil diterima. ID transaksi: ABC123","sub_text":"","posted_at":"2026-06-01T09:30:00.000Z"}'
```

Cek invoice:

```bash
curl -H "Authorization: Bearer TOKEN_ANDA" http://SERVER_IP:8099/api/invoices
```

## Dokumentasi

- [Arsitektur](docs/architecture.md)
- [Backend Deployment](docs/deployment.md)
- [API Reference](docs/api.md)
- [Android Setup](docs/android-setup.md)
- [Testing](docs/testing.md)
- [Roadmap SaaS](docs/roadmap.md)
