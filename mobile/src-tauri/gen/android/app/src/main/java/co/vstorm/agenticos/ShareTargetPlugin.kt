package co.vstorm.agenticos

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import android.util.Base64
import android.webkit.WebView
import java.io.ByteArrayOutputStream
import java.io.IOException
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSArray
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/** A file larger than this is named back rather than read into memory. */
private const val MAX_BYTES = 20L * 1024 * 1024

/**
 * "Share → AgenticOS" (#2097): what another app shared - text, a link, photos,
 * files - held until the console takes it into a new message.
 *
 * It is read here, where the content URIs' read grant lives, and handed over
 * whole: the console's composer uploads files it is given, as it does a
 * pasted screenshot.
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
        val files = JSArray()
        val refused = JSArray()
        for (uri in streams(intent)) {
            // One file that cannot be read - no grant, gone, too large - is named
            // back to the person; it must not lose the rest, or crash the app.
            try {
                val (name, size) = describe(uri)
                val bytes = if (size > MAX_BYTES) null else read(uri)
                if (bytes == null) {
                    refused.put(name)
                    continue
                }
                files.put(
                    JSObject()
                        .put("name", name)
                        .put("mimeType", activity.contentResolver.getType(uri) ?: "application/octet-stream")
                        .put("data", Base64.encodeToString(bytes, Base64.NO_WRAP)),
                )
            } catch (e: SecurityException) {
                refused.put(uri.lastPathSegment ?: "shared")
            } catch (e: IOException) {
                refused.put(uri.lastPathSegment ?: "shared")
            }
        }
        pending = JSObject().put("text", text).put("files", files).put("refused", refused)
        // Taken once: a later launch of the same activity must not share it again.
        intent.action = null
    }

    /** The file's bytes, or null for one with no size given that turns out too large. */
    private fun read(uri: Uri): ByteArray? =
        activity.contentResolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream()
            val chunk = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(chunk)
                if (read < 0) break
                if (out.size() + read > MAX_BYTES) return null
                out.write(chunk, 0, read)
            }
            out.toByteArray()
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

    private fun describe(uri: Uri): Pair<String, Long> {
        activity.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val name = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val size = cursor.getColumnIndex(OpenableColumns.SIZE)
                return Pair(
                    if (name >= 0) cursor.getString(name) else uri.lastPathSegment ?: "shared",
                    if (size >= 0 && !cursor.isNull(size)) cursor.getLong(size) else 0L,
                )
            }
        }
        return Pair(uri.lastPathSegment ?: "shared", 0L)
    }

    /** What was shared since the console last asked, or an empty object. */
    @Command
    fun take(invoke: Invoke) {
        val shared = pending ?: JSObject()
        pending = null
        invoke.resolve(shared)
    }
}
