package co.vstorm.agenticos

import android.app.Activity
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

@InvokeArg
class PinArgs {
    lateinit var id: String
    lateinit var name: String

    /** The agent's face, a PNG drawn for an adaptive icon, base64. */
    lateinit var icon: String
}

/**
 * An agent pinned to the home screen (#2097): a launcher shortcut wearing the
 * agent's face that opens a new chat with it, through the same
 * agenticos://activity link the app's other shortcuts use. It also joins the
 * app icon's long-press list. The launcher asks the person to place it; one
 * that cannot pin says so in the answer.
 */
@TauriPlugin
class PinShortcutPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun pin(invoke: Invoke) {
        val args = invoke.parseArgs(PinArgs::class.java)
        val bytes = Base64.decode(args.icon, Base64.DEFAULT)
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        if (bitmap == null) {
            invoke.reject("The agent's face is not an image.")
            return
        }
        val link =
            Uri.Builder()
                .scheme("agenticos")
                .authority("activity")
                .path("/open")
                .appendQueryParameter("path", "/chat?with=${args.id}")
                .build()
        val shortcut =
            ShortcutInfoCompat.Builder(activity, "agent-${args.id}")
                .setShortLabel(args.name)
                .setLongLabel(args.name)
                .setIcon(IconCompat.createWithAdaptiveBitmap(bitmap))
                .setIntent(Intent(Intent.ACTION_VIEW, link, activity, MainActivity::class.java))
                .build()
        ShortcutManagerCompat.pushDynamicShortcut(activity, shortcut)
        val pinnable = ShortcutManagerCompat.isRequestPinShortcutSupported(activity)
        if (pinnable) ShortcutManagerCompat.requestPinShortcut(activity, shortcut, null)
        invoke.resolve(JSObject().put("pinned", pinnable))
    }
}
