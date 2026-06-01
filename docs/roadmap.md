# Roadmap SaaS

## Phase 1 - MVP Core

Status: selesai tahap awal.

- Android listener
- webhook receiver
- PostgreSQL persistence
- invoice API
- payment event API
- parser nominal dan transaction ref
- matching invoice by amount

## Phase 2 - Hardening

- endpoint invoice detail by `external_id`
- better duplicate handling
- unmatched event reprocessing
- structured error logs
- admin token terpisah dari Android token
- backup database

## Phase 3 - Merchant/SaaS Foundation

- tabel `merchants` - done
- tabel `api_tokens` - done
- tabel `devices` - done
- invoice per merchant - done
- device per merchant - done
- token per merchant/device - done
- rate limit

## Phase 4 - Dashboard

- dashboard invoice
- dashboard payment events
- filter by status
- manual match/unmatch
- export CSV

## Phase 5 - Callback Merchant

- merchant callback URL
- signed callback payload
- retry queue
- callback status history

## Phase 6 - Production Readiness

- HTTPS reverse proxy
- secrets management
- monitoring service uptime
- Android heartbeat
- alert jika device offline
- audit log
- test coverage
- release APK signing

## Risiko Yang Perlu Diingat

- Notifikasi Android bukan API resmi payment provider.
- Format notifikasi bisa berubah.
- Device bisa offline atau izin listener dicabut.
- Matching amount saja belum aman untuk transaksi dengan nominal sama.
- Production perlu validasi dan rekonsiliasi tambahan.
