package co.vstorm.agenticos

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.webkit.WebView
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/**
 * "Share → AgenticOS" (#2097): what another app shared - text, a link, photos,
 * files - held until the console takes it into a new message.
 *
 * It is read here, where the content URIs' read grant lives (`SharedFiles`),
 * and handed over whole: the console's composer uploads files it is given, as
 * it does a pasted screenshot.
 */
@TauriPlugin
class ShareTargetPlugin(private val activity: Activity) : Plugin(activity) {
    private var pending: JSObject? = null

    override fun load(webView: WebView) {
        super.load(webView)
        receive(activity.intent)
    }

    override fun onNewIntent(intent: Intent) {
        receive(intent)
    }

    private fun receive(intent: Intent?) {
        if (intent == null) return
        if (intent.action != Intent.ACTION_SEND && intent.action != Intent.ACTION_SEND_MULTIPLE) return
        val text = listOfNotNull(
            intent.getStringExtra(Intent.EXTRA_SUBJECT),
            intent.getStringExtra(Intent.EXTRA_TEXT),
        ).joinToString("\n").trim()
        pending = SharedFiles.collect(activity, streams(intent), text)
        // Taken once: a later launch of the same activity must not share it again.
        intent.action = null
    }

    @Suppress("DEPRECATION")
    private fun streams(intent: Intent): List<Uri> =
        if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            } else {
                intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)
            } ?: emptyList()
        } else {
            listOfNotNull(
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
                } else {
                    intent.getParcelableExtra(Intent.EXTRA_STREAM)
                },
            )
        }

    /** What was shared since the console last asked, or an empty object. */
    @Command
    fun take(invoke: Invoke) {
        val shared = pending ?: JSObject()
        pending = null
        invoke.resolve(shared)
    }
}
