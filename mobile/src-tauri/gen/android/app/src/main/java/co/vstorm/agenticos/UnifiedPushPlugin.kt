package co.vstorm.agenticos

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
class RegisterArgs {
    lateinit var vapid: String
}

/**
 * The console's handle on push while the app is closed (#2097): which
 * distributors the phone has, the endpoint one handed over, and turning it on
 * and off. `PushMessagingService` receives what the distributor sends.
 */
@TauriPlugin
class UnifiedPushPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun status(invoke: Invoke) {
        val store = PushMessagingService.store(activity)
        val distributors = JSArray()
        UnifiedPush.getDistributors(activity).forEach { distributors.put(it) }
        val status = JSObject().put("distributors", distributors)
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
