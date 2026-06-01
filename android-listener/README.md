# Notifier Listener Android

Aplikasi Android native Kotlin untuk menangkap notifikasi aplikasi lain melalui `NotificationListenerService` dan mengirim data ke webhook via HTTP POST JSON.

## Build

```bash
gradle :app:assembleDebug
```

APK debug akan dibuat di:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Payload Webhook

```json
{
  "package": "com.whatsapp",
  "title": "Nama pengirim",
  "text": "Isi notifikasi",
  "sub_text": "",
  "posted_at": "2026-06-01T12:00:00Z"
}
```
