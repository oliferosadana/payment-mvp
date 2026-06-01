package com.local.notifierlistener

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

const val PREFS_NAME = "notifier_listener"
const val KEY_WEBHOOK_URL = "webhook_url"
const val KEY_API_TOKEN = "api_token"
const val KEY_PACKAGE_FILTER = "package_filter"

class NotificationRelayService : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val webhookUrl = prefs.getString(KEY_WEBHOOK_URL, "").orEmpty()
        val token = prefs.getString(KEY_API_TOKEN, "").orEmpty()
        if (webhookUrl.isBlank()) return

        val allowedPackages = prefs.getString(KEY_PACKAGE_FILTER, "")
            .orEmpty()
            .split(',', '\n', '\r', '\t', ' ')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .toSet()

        if (allowedPackages.isNotEmpty() && sbn.packageName !in allowedPackages) return

        val extras = sbn.notification.extras
        val payload = mapOf(
            "package" to sbn.packageName,
            "title" to extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty(),
            "text" to extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty(),
            "sub_text" to extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString().orEmpty(),
            "posted_at" to Instant.ofEpochMilli(sbn.postTime).toString()
        )

        Thread { postJson(webhookUrl, token, payload.toJson()) }.start()
    }

    private fun postJson(webhookUrl: String, token: String, json: String) {
        runCatching {
            val connection = URL(webhookUrl).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 10_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (token.isNotBlank()) {
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { it.write(json) }
            val stream = if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream
            stream?.close()
            connection.disconnect()
        }
    }
}

private fun Map<String, String>.toJson(): String = entries.joinToString(
    prefix = "{",
    postfix = "}"
) { (key, value) -> "\"${key.escapeJson()}\":\"${value.escapeJson()}\"" }

private fun String.escapeJson(): String = buildString {
    for (char in this@escapeJson) {
        when (char) {
            '\\' -> append("\\\\")
            '"' -> append("\\\"")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> append(char)
        }
    }
}
