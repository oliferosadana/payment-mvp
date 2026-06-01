# Arsitektur

## Tujuan MVP

MVP ini membuktikan flow dasar payment detection:

1. Android membaca notifikasi dari aplikasi target.
2. Android mengirim data notifikasi ke backend.
3. Backend menyimpan event ke PostgreSQL.
4. Backend mem-parse nominal dan ID transaksi.
5. Backend mencocokkan event dengan invoice pending.
6. Invoice berubah menjadi `paid` jika cocok.

## Komponen

### Android Listener

Lokasi: `android-listener/`

Fitur:

- `NotificationListenerService`
- filter package berdasarkan input user
- webhook URL
- API key/token
- test webhook
- kirim payload JSON ke backend

Payload utama:

```json
{
  "package": "com.gojek.resto",
  "title": "Pembayaran QRIS diterima!",
  "text": "Rp1 berhasil diterima. ID transaksi: tKT82AID",
  "sub_text": "",
  "posted_at": "2026-06-01T09:08:00.109Z"
}
```

### Backend Payment MVP

Lokasi: `backend/`

Fitur:

- HTTP server Python standard library
- token auth via `Authorization: Bearer <token>`
- endpoint invoice
- endpoint webhook
- parser notifikasi QRIS/Gojek
- matching invoice by amount
- PostgreSQL persistence

### Database

Database: `payment_mvp`

Tabel:

- `invoices`
- `payment_events`

## Matching Rule MVP

Saat event masuk:

1. Parse nominal dari teks `Rp...`.
2. Parse transaction reference dari `ID transaksi: ...`.
3. Jika `transaction_ref` sudah pernah ada, event ditandai `duplicate`.
4. Jika amount ditemukan, cari invoice `pending` dengan amount sama.
5. Jika invoice ditemukan, invoice menjadi `paid`, event menjadi `matched`.
6. Jika tidak ditemukan, event menjadi `unmatched`.

## Batasan MVP

- Matching hanya berdasarkan amount.
- Belum ada multi-merchant.
- Belum ada callback ke merchant.
- Belum ada dashboard web.
- Belum ada device heartbeat.
- Notification listener bukan payment API resmi.


## SaaS Foundation v0.2

Backend sekarang sudah multi-tenant secara dasar:

- `merchants` menyimpan tenant/merchant.
- `api_tokens` menyimpan token `admin`, `merchant`, dan `device`.
- `devices` menyimpan Android listener device per merchant.
- `invoices` memiliki `merchant_id`.
- `payment_events` memiliki `merchant_id` dan `device_id`.

Token usage:

- Admin token: membuat merchant dan melihat semua data.
- Merchant token: membuat/list invoice dan melihat event milik merchant tersebut.
- Device token: dipakai Android listener untuk `POST /webhook`.

Matching v0.2 mencari invoice `pending` dengan merchant yang sama dan amount yang sama. Jika ada lebih dari satu kandidat, event menjadi `needs_review`.

## SaaS v0.4

- Dashboard merchant interaktif berbasis token browser.
- Manual match untuk event `needs_review`.
- Callback attempts disimpan di tabel `callback_attempts`.
- Callback retry endpoint tersedia.
- Reverse proxy config disiapkan untuk Nginx + Certbot.
