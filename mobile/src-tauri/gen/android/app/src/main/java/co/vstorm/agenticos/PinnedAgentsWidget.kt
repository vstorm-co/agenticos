package co.vstorm.agenticos

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

private const val STORE = "agenticos.pinned"
private const val SLOTS = 4
private const val KEPT = 8

private val FACES = intArrayOf(R.id.pinned_face_0, R.id.pinned_face_1, R.id.pinned_face_2, R.id.pinned_face_3)
private val NAMES = intArrayOf(R.id.pinned_name_0, R.id.pinned_name_1, R.id.pinned_name_2, R.id.pinned_name_3)
private val SLOT_IDS = intArrayOf(R.id.pinned_slot_0, R.id.pinned_slot_1, R.id.pinned_slot_2, R.id.pinned_slot_3)

/** One agent pinned from the console, as the widget keeps it. */
data class PinnedAgent(val id: String, val name: String, val face: File)

/**
 * The agents pinned from the console, with their faces (#2305): Android's
 * answer to iOS's pinned-agents widget, beside the launcher shortcut
 * `PinShortcutPlugin` already places. A tap on a face is a new chat with that
 * agent, through the same agenticos://activity link the shortcut opens.
 */
class PinnedAgentsWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        draw(context, manager, ids)
    }

    companion object {
        /** Keep an agent first in the widget's list, its face beside it, and redraw. */
        fun remember(context: Context, id: String, name: String, face: ByteArray) {
            val dir = File(context.filesDir, "pinned").apply { mkdirs() }
            val file = File(dir, "${id.filter { it.isLetterOrDigit() || it == '-' }}.png")
            file.writeBytes(face)
            val agents = read(context).filter { it.id != id }
            val kept = listOf(PinnedAgent(id, name, file)) + agents
            kept.drop(KEPT).forEach { it.face.delete() }
            val json = JSONArray()
            kept.take(KEPT).forEach {
                json.put(JSONObject().put("id", it.id).put("name", it.name).put("face", it.face.path))
            }
            context.getSharedPreferences(STORE, Context.MODE_PRIVATE).edit()
                .putString("agents", json.toString())
                .apply()
            refresh(context)
        }

        fun clear(context: Context) {
            read(context).forEach { it.face.delete() }
            context.getSharedPreferences(STORE, Context.MODE_PRIVATE).edit().clear().apply()
            val ids = androidx.core.content.pm.ShortcutManagerCompat.getShortcuts(context,
                androidx.core.content.pm.ShortcutManagerCompat.FLAG_MATCH_DYNAMIC or
                androidx.core.content.pm.ShortcutManagerCompat.FLAG_MATCH_PINNED)
                .filter { it.id.startsWith("agent-") }.map { it.id }
            androidx.core.content.pm.ShortcutManagerCompat.disableShortcuts(context, ids, null)
            androidx.core.content.pm.ShortcutManagerCompat.removeDynamicShortcuts(context, ids)
            refresh(context)
        }

        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, PinnedAgentsWidget::class.java))
            if (ids.isNotEmpty()) draw(context, manager, ids)
        }

        private fun read(context: Context): List<PinnedAgent> {
            val raw = context.getSharedPreferences(STORE, Context.MODE_PRIVATE).getString("agents", null)
                ?: return emptyList()
            val json = JSONArray(raw)
            return (0 until json.length()).map { index ->
                val item = json.getJSONObject(index)
                PinnedAgent(item.getString("id"), item.getString("name"), File(item.getString("face")))
            }
        }

        private fun chat(context: Context, id: String, request: Int): PendingIntent {
            val link = Uri.Builder()
                .scheme("agenticos")
                .authority("activity")
                .path("/open")
                .appendQueryParameter("path", "/chat?with=$id")
                .build()
            val intent = Intent(Intent.ACTION_VIEW, link).setPackage(context.packageName)
            return PendingIntent.getActivity(
                context,
                request,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }

        private fun draw(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val agents = read(context).take(SLOTS)
            val views = RemoteViews(context.packageName, R.layout.widget_pinned)
            views.setViewVisibility(R.id.pinned_empty, if (agents.isEmpty()) View.VISIBLE else View.GONE)
            views.setViewVisibility(R.id.pinned_row, if (agents.isEmpty()) View.GONE else View.VISIBLE)
            for (slot in 0 until SLOTS) {
                val agent = agents.getOrNull(slot)
                if (agent == null) {
                    views.setViewVisibility(SLOT_IDS[slot], View.GONE)
                    continue
                }
                views.setViewVisibility(SLOT_IDS[slot], View.VISIBLE)
                views.setTextViewText(NAMES[slot], agent.name)
                val face = BitmapFactory.decodeFile(agent.face.path)
                if (face != null) {
                    views.setImageViewBitmap(FACES[slot], face)
                } else {
                    views.setImageViewResource(FACES[slot], R.drawable.ic_shortcut_chat)
                }
                views.setOnClickPendingIntent(SLOT_IDS[slot], chat(context, agent.id, 100 + slot))
            }
            manager.updateAppWidget(ids, views)
        }
    }
}
