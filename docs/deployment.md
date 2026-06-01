# Backend Deployment

Backend berjalan sebagai systemd service bernama `notifier-webhook`.

## Requirement

- Debian 12 atau setara
- Python 3.11+
- PostgreSQL 15+
- `psql` CLI tersedia

## File Penting

```text
/opt/notifier-webhook/server.py
/etc/default/notifier-webhook
/etc/systemd/system/notifier-webhook.service
```

## Environment

Contoh `/etc/default/notifier-webhook`:

```bash
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8099
WEBHOOK_TOKEN=change-this-token
WEBHOOK_DATA_DIR=/var/log/notifier-webhook
PAYMENT_DB=payment_mvp
```

## Database

Buat database:

```bash
su - postgres -c "createdb payment_mvp"
```

Apply schema:

```bash
su - postgres -c "psql -d payment_mvp -f /path/to/backend/schema.sql"
```

## Install Service

Copy backend:

```bash
mkdir -p /opt/notifier-webhook
cp backend/server.py /opt/notifier-webhook/server.py
chmod +x /opt/notifier-webhook/server.py
cp backend/notifier-webhook.service /etc/systemd/system/notifier-webhook.service
```

Reload dan start:

```bash
systemctl daemon-reload
systemctl enable --now notifier-webhook
```

Cek status:

```bash
systemctl status notifier-webhook
curl http://127.0.0.1:8099/health
```

## Logs

```bash
journalctl -u notifier-webhook -f
```

## Restart

Setelah ubah config atau source:

```bash
systemctl restart notifier-webhook
```

## Reverse Proxy / HTTPS

Contoh konfigurasi Nginx tersedia di:

```text
deploy/nginx/payment-saas.conf
```

Untuk production, arahkan DNS ke server lalu gunakan Certbot:

```bash
apt install nginx certbot python3-certbot-nginx
cp deploy/nginx/payment-saas.conf /etc/nginx/sites-available/payment-saas.conf
ln -s /etc/nginx/sites-available/payment-saas.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d payment.example.com
```
