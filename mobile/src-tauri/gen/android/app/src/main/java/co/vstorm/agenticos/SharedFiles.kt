package co.vstorm.agenticos

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import app.tauri.plugin.JSArray
import app.tauri.plugin.JSObject
import java.io.ByteArrayOutputStream
import java.io.IOException

/** A file larger than this is named back rather than read into memory. */
private const val MAX_BYTES = 20L * 1024 * 1024

/**
 * Files handed to the console - shared from another app, picked in the attach
 * sheet, just photographed - read where the read grant lives, in the shape
 * the app's `take_shared` and the console's `parseShared` read:
 * `{text, files: [{name, mimeType, data}], refused: [name]}`.
 *
 * One file that cannot be read - no grant, gone, too large - is named in
 * `refused`; it must not lose the rest, or crash the app.
 */
object SharedFiles {
    fun collect(context: Context, uris: List<Uri>, text: String = ""): JSObject {
        val files = JSArray()
        val refused = JSArray()
        for (uri in uris) {
            try {
                val (name, size) = describe(context, uri)
                val bytes = if (size > MAX_BYTES) null else read(context, uri)
                if (bytes == null) {
                    refused.put(name)
                    continue
                }
                files.put(
                    JSObject()
                        .put("name", name)
                        .put("mimeType", context.contentResolver.getType(uri) ?: "application/octet-stream")
                        .put("data", Base64.encodeToString(bytes, Base64.NO_WRAP)),
                )
            } catch (e: SecurityException) {
                refused.put(uri.lastPathSegment ?: "shared")
            } catch (e: IOException) {
                refused.put(uri.lastPathSegment ?: "shared")
            }
        }
        return JSObject().put("text", text).put("files", files).put("refused", refused)
    }

    private fun describe(context: Context, uri: Uri): Pair<String, Long> {
        context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
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

    /** The file's bytes, or null for one with no size given that turns out too large. */
    private fun read(context: Context, uri: Uri): ByteArray? =
        context.contentResolver.openInputStream(uri)?.use { input ->
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
}
