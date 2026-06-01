# Android Setup

Aplikasi Android berada di folder `android-listener/`.

## Build APK

Di server/build machine yang punya Android SDK:

```bash
cd android-listener
gradle :app:assembleDebug
```

APK debug:

```text
android-listener/app/build/outputs/apk/debug/app-debug.apk
```

## Konfigurasi Aplikasi

Isi form berikut di aplikasi:

```text
Webhook URL:
http://SERVER_IP:8099/webhook

API Key / Token:
isi WEBHOOK_TOKEN dari backend

Package filter:
com.gojek.resto
```

Tekan `Simpan Pengaturan`.

## Permission

Tekan `Buka Notification Access`, lalu aktifkan izin untuk `Notifier Listener`.

## Test Webhook

Tekan `Test Webhook` dari aplikasi.

Jika berhasil, status akan menjadi:

```text
Berhasil (200)
```

Di backend, event test akan diterima sebagai:

```json
{
  "event": "test_webhook",
  "source": "notifier_listener"
}
```

## Package Filter

Aplikasi hanya mengirim notifikasi dari package yang cocok persis.

Contoh:

```text
com.gojek.resto
com.whatsapp
org.telegram.messenger
```

Jika filter kosong, semua notifikasi akan dikirim.

## Device Name

Versi terbaru aplikasi memiliki field `Device Name`.

Contoh:

```text
Kasir 1
Outlet A
Device QRIS Utama
```

Field ini dikirim ke backend sebagai `device_name`, lalu backend membuat atau memperbarui record pada tabel `devices`.
