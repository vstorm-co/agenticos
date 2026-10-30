package co.vstorm.agenticos

import android.Manifest
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import app.tauri.annotation.Permission
import app.tauri.annotation.PermissionCallback
import app.tauri.PermissionState
import android.app.Activity
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSArray
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.unifiedpush.android.connector.UnifiedPush

@InvokeArg
class PushSessionArgs { lateinit var sessionId: String }

@InvokeArg
class RegisterArgs {
    lateinit var vapid: String
}

/**
 * The console's handle on push while the app is closed (#2097): which
 * distributors the phone has, the endpoint one handed over, and turning it on
 * and off. `PushMessagingService` receives what the distributor sends.
 */
@TauriPlugin(permissions = [Permission(strings = [Manifest.permission.POST_NOTIFICATIONS], alias = "notifications")])
class UnifiedPushPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun bindSession(invoke: Invoke) {
        val args = invoke.parseArgs(PushSessionArgs::class.java)
        val store = PushMessagingService.store(activity)
        if (store.getString("session", null) != args.sessionId) {
            NotificationManagerCompat.from(activity).cancelAll()
        }
        store.edit().putString("session", args.sessionId).apply()
        invoke.resolve()
    }

    @Command
    fun openSettings(invoke: Invoke) {
        activity.runOnUiThread {
            try {
                activity.startActivity(android.content.Intent(
                    android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    android.net.Uri.parse("package:" + activity.packageName)
                ))
                invoke.resolve()
            } catch (error: android.content.ActivityNotFoundException) {
                invoke.reject("App settings could not be opened.")
            }
        }
    }

    @Command
    fun status(invoke: Invoke) {
        val store = PushMessagingService.store(activity)
        val distributors = JSArray()
        UnifiedPush.getDistributors(activity).forEach { distributors.put(it) }
        val permission = if (NotificationManagerCompat.from(activity).areNotificationsEnabled()) "granted"
            else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && getPermissionState("notifications") != PermissionState.DENIED) "undetermined"
            else "denied"
        val status = JSObject().put("distributors", distributors).put("permission", permission)
        UnifiedPush.getAckDistributor(activity)?.let { status.put("distributor", it) }
        store.getString("failed", null)?.let { status.put("failed", it) }
        val endpoint = store.getString("endpoint", null)
        val p256dh = store.getString("p256dh", null)
        val auth = store.getString("auth", null)
        if (endpoint != null && p256dh != null && auth != null) {
            status.put("endpoint", endpoint).put("p256dh", p256dh).put("auth", auth)
        }
        invoke.resolve(status)
    }

    /** Use the phone's distributor - asking which, when there are several - and register with it. */
    @Command
    fun register(invoke: Invoke) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && getPermissionState("notifications") != PermissionState.GRANTED) {
            requestPermissionForAlias("notifications", invoke, "notificationPermissionCallback")
            return
        }
        registerWithDistributor(invoke)
    }

    @PermissionCallback
    fun notificationPermissionCallback(invoke: Invoke) {
        if (getPermissionState("notifications") == PermissionState.GRANTED) registerWithDistributor(invoke)
        else invoke.resolve(JSObject().put("registered", false))
    }

    private fun registerWithDistributor(invoke: Invoke) {
        val args = invoke.parseArgs(RegisterArgs::class.java)
        UnifiedPush.tryUseCurrentOrDefaultDistributor(activity) { ready ->
            if (!ready) {
                invoke.resolve(JSObject().put("registered", false))
                return@tryUseCurrentOrDefaultDistributor
            }
            try {
                UnifiedPush.register(activity, vapid = args.vapid)
                invoke.resolve(JSObject().put("registered", true))
            } catch (e: Exception) {
                invoke.reject(e.message ?: "The distributor refused the registration.")
            }
        }
    }

    @Command
    fun unregister(invoke: Invoke) {
        UnifiedPush.unregister(activity)
        PushMessagingService.store(activity).edit().clear().apply()
        invoke.resolve()
    }
}
