package co.vstorm.agenticos

import android.app.Activity
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.text.format.DateFormat
import android.widget.RemoteViews
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Plugin
import java.util.Date

private const val STORE = "agenticos.widget"

/**
 * The home-screen widget (#2097): approvals waiting for you and your runs in
 * flight, as the console last counted them.
 *
 * Nothing here reads the server - the app holds no session of its own, the
 * console does - so the numbers are the console's, kept when it counts them
 * and shown with the time they were counted. Push will refresh them while the
 * app is closed; until then an old number says it is old.
 */
class GlanceWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        draw(context, manager, ids)
    }

    companion object {
        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, GlanceWidget::class.java))
            if (ids.isNotEmpty()) draw(context, manager, ids)
        }

        private fun link(context: Context, path: String, request: Int): PendingIntent {
            val intent = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("agenticos://activity/open?path=" + Uri.encode(path)),
            ).setPackage(context.packageName)
            return PendingIntent.getActivity(
                context,
                request,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }

        private fun draw(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val store = context.getSharedPreferences(STORE, Context.MODE_PRIVATE)
            val counted = store.getLong("updatedAt", 0L)
            val approvals = store.getInt("approvals", 0)
            val running = store.getInt("running", 0)
            val views = RemoteViews(context.packageName, R.layout.widget_glance)
            val resources = context.resources
            views.setTextViewText(R.id.widget_approvals_count, if (counted == 0L) "–" else approvals.toString())
            views.setTextViewText(
                R.id.widget_approvals_label,
                resources.getQuantityString(R.plurals.widget_approvals, approvals),
            )
            views.setTextViewText(R.id.widget_running_count, if (counted == 0L) "–" else running.toString())
            views.setTextViewText(
                R.id.widget_running_label,
                resources.getQuantityString(R.plurals.widget_running, running),
            )
            views.setTextViewText(
                R.id.widget_updated,
                if (counted == 0L) context.getString(R.string.widget_never)
                else DateFormat.getTimeFormat(context).format(Date(counted)),
            )
            views.setOnClickPendingIntent(R.id.widget_root, link(context, "/dashboard", 1))
            views.setOnClickPendingIntent(R.id.widget_approvals, link(context, "/runs?tab=approvals", 2))
            views.setOnClickPendingIntent(R.id.widget_running, link(context, "/runs", 3))
            manager.updateAppWidget(ids, views)
        }
    }
}

@InvokeArg
class GlanceArgs {
    var approvals: Int = 0
    var running: Int = 0
}

/** The console's half: the counts it just read, kept for the widget. */
@TauriPlugin
class WidgetPlugin(private val activity: Activity) : Plugin(activity) {
    @Command
    fun update(invoke: Invoke) {
        val args = invoke.parseArgs(GlanceArgs::class.java)
        activity.getSharedPreferences(STORE, Context.MODE_PRIVATE).edit()
            .putInt("approvals", args.approvals)
            .putInt("running", args.running)
            .putLong("updatedAt", System.currentTimeMillis())
            .apply()
        GlanceWidget.refresh(activity)
        invoke.resolve()
    }
}
