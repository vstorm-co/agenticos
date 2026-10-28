package co.vstorm.agenticos

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONException
import org.json.JSONObject
import org.unifiedpush.android.connector.FailedReason
import org.unifiedpush.android.connector.PushService
import org.unifiedpush.android.connector.data.PushEndpoint
import org.unifiedpush.android.connector.data.PushMessage

private const val STORE = "agenticos.push"
private const val CHANNEL = "agenticos.push"

/**
 * Push while the app is closed (#2097), through a UnifiedPush distributor -
 * ntfy, from F-Droid or the Play Store, against ntfy.sh or a company's own
 * server - rather than Firebase.
 *
 * The distributor hands this a Web Push endpoint and keys; the console sends
 * them to the server as it would a browser's subscription, and the server
 * pushes to it exactly as to a browser. A message arrives decrypted, in the
 * shape the server sends a browser - `{title, body, url, tag}` - and is drawn
 * here, its tap opening the console page it names.
 */
class PushMessagingService : PushService() {
    override fun onNewEndpoint(endpoint: PushEndpoint, instance: String) {
        val keys = endpoint.pubKeySet
        store(this).edit()
            .putString("endpoint", endpoint.url)
            .putString("p256dh", keys?.pubKey)
            .putString("auth", keys?.auth)
            .remove("failed")
            .apply()
    }

    override fun onRegistrationFailed(reason: FailedReason, instance: String) {
        store(this).edit().remove("endpoint").remove("p256dh").remove("auth").putString("failed", reason.name).apply()
    }

    override fun onUnregistered(instance: String) {
        store(this).edit().remove("endpoint").remove("p256dh").remove("auth").remove("failed").apply()
    }

    override fun onMessage(message: PushMessage, instance: String) {
        // Only what the server encrypted to this app's keys: a plain message
        // could have come from anybody who learnt the endpoint.
        if (!message.decrypted) return
        val push = try {
            JSONObject(String(message.content, Charsets.UTF_8))
        } catch (e: JSONException) {
            return
        }
        show(this, push)
    }

    companion object {
        fun store(context: Context) = context.getSharedPreferences(STORE, Context.MODE_PRIVATE)

        private fun show(context: Context, push: JSONObject) {
            val system = context.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                system.createNotificationChannel(
                    NotificationChannel(
                        CHANNEL,
                        context.getString(R.string.push_channel),
                        NotificationManager.IMPORTANCE_HIGH,
                    ),
                )
            }
            val expected = store(context).getString("session", null) ?: return
            if (push.optString("session_id") != expected) return
            val path = push.optString("url").takeIf { it.startsWith("/") && !it.startsWith("//") } ?: "/dashboard"
            val open = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("agenticos://activity/open?path=" + Uri.encode(path) + "&push_session=" + Uri.encode(expected)),
            ).setPackage(context.packageName)
            val tag = push.optString("tag").ifEmpty { path }
            val notification = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_agenticos)
                .setContentTitle(push.optString("title").ifEmpty { context.getString(R.string.app_name) })
                .setContentText(push.optString("body"))
                .setStyle(NotificationCompat.BigTextStyle().bigText(push.optString("body")))
                .setAutoCancel(true)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setContentIntent(
                    PendingIntent.getActivity(
                        context,
                        tag.hashCode(),
                        open,
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                    ),
                )
                .build()
            try {
                NotificationManagerCompat.from(context).notify(tag.hashCode(), notification)
            } catch (e: SecurityException) {
                // Notifications not allowed: the message waits in the console's inbox.
            }
        }
    }
}
