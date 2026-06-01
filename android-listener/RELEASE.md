# Android Release Notes

Current build output on build server:

```text
/root/notifier-listener-android/app/build/outputs/apk/debug/app-debug.apk
```

For first merchant pilot, debug APK is acceptable only for internal testing.

Before wider distribution:

1. Create release keystore.
2. Configure signed release build.
3. Set version code and version name.
4. Add final launcher icon and app name.
5. Test notification access after reinstall/update.
6. Document battery optimization settings per Android vendor.

Required app settings:

```text
Webhook URL: https://your-domain.example.com/webhook
API Key / Token: device_token
Device Name: merchant outlet/cashier name
Package filter: target payment app package name
```
