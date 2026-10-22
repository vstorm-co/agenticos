package co.vstorm.agenticos

import android.app.Activity
import android.content.Context
import android.content.RestrictionsManager
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/**
 * What the organization's device management set for the app (#2097), as
 * Android's managed configurations deliver it: `app_restrictions.xml` names
 * the keys, an EMM fills them in. Read as given; the rules are the Rust side's.
 */
@TauriPlugin
class ManagedConfigPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun read(invoke: Invoke) {
        val manager = activity.getSystemService(Context.RESTRICTIONS_SERVICE) as RestrictionsManager
        val given = manager.applicationRestrictions
        val policy = JSObject()
        given.getString("serverUrl")?.let { policy.put("serverUrl", it) }
        if (given.containsKey("serverLocked")) policy.put("serverLocked", given.getBoolean("serverLocked"))
        given.getString("biometricLock")?.let { policy.put("biometricLock", it) }
        invoke.resolve(policy)
    }
}
