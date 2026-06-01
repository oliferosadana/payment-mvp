package com.local.notifierlistener

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : Activity() {
    private lateinit var webhookInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var packageFilterInput: EditText
    private lateinit var statusText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        webhookInput = findViewById(R.id.webhookInput)
        tokenInput = findViewById(R.id.tokenInput)
        packageFilterInput = findViewById(R.id.packageFilterInput)
        statusText = findViewById(R.id.statusText)

        webhookInput.setText(prefs.getString(KEY_WEBHOOK_URL, ""))
        tokenInput.setText(prefs.getString(KEY_API_TOKEN, ""))
        packageFilterInput.setText(prefs.getString(KEY_PACKAGE_FILTER, ""))

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            saveSettings()
            Toast.makeText(this, "Pengaturan tersimpan", Toast.LENGTH_SHORT).show()
        }

        findViewById<Button>(R.id.testWebhookButton).setOnClickListener {
            saveSettings()
            testWebhook()
        }

        findViewById<Button>(R.id.permissionButton).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
    }

    private fun saveSettings() {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_WEBHOOK_URL, webhookInput.text.toString().trim())
            .putString(KEY_API_TOKEN, tokenInput.text.toString().trim())
            .putString(KEY_PACKAGE_FILTER, packageFilterInput.text.toString().trim())
            .apply()
    }

    private fun testWebhook() {
        val webhookUrl = webhookInput.text.toString().trim()
        val token = tokenInput.text.toString().trim()
        if (webhookUrl.isBlank()) {
            statusText.text = "URL kosong"
            return
        }

        statusText.text = "Menguji..."
        Thread {
            val result = runCatching {
                val connection = URL(webhookUrl).openConnection() as HttpURLConnection
                connection.requestMethod = "POST"
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                if (token.isNotBlank()) {
                    connection.setRequestProperty("Authorization", "Bearer $token")
                }
                OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use {
                    it.write("{\"event\":\"test_webhook\",\"source\":\"notifier_listener\"}")
                }
                val code = connection.responseCode
                connection.disconnect()
                code
            }

            runOnUiThread {
                statusText.text = result.fold(
                    onSuccess = { code -> if (code in 200..299) "Berhasil ($code)" else "Gagal ($code)" },
                    onFailure = { error -> "Gagal: ${error.javaClass.simpleName}" }
                )
            }
        }.start()
    }
}
