# First Merchant Readiness Checklist

## Server

- Put the service behind Nginx reverse proxy.
- Use HTTPS before exposing to the internet.
- Bind backend to localhost when Nginx is active: `WEBHOOK_HOST=127.0.0.1`.
- Keep port `8099` closed from public internet.
- Rotate admin token before production use.
- Use unique merchant/device tokens per merchant.

## Database Backup

Create daily PostgreSQL backup:

```bash
mkdir -p /var/backups/payment-mvp
pg_dump payment_mvp | gzip > /var/backups/payment-mvp/payment_mvp-$(date +%F).sql.gz
```

Cron example:

```cron
15 2 * * * postgres pg_dump payment_mvp | gzip > /var/backups/payment-mvp/payment_mvp-$(date +\%F).sql.gz
```

## Android

- Use device token, not merchant/admin token.
- Fill package filter with the target app package, for example `com.gojek.resto`.
- Disable battery optimization for the listener phone.
- Keep notification access enabled.
- Use one device name per outlet/cashier.

## Operational Test

Before onboarding the first merchant:

1. Create merchant.
2. Copy merchant token and device token.
3. Configure Android with device token.
4. Create invoice from dashboard.
5. Trigger small payment notification.
6. Confirm invoice becomes `paid`.
7. Confirm callback attempt is created if callback URL is set.
