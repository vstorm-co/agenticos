package co.vstorm.agenticos

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Plugin

/**
 * What the agents are doing, kept on the phone's lock screen and in its shade:
 * Android's counterpart of the iOS Live Activity in the Dynamic Island (#2097).
 *
 * The console decides what is live and says so through the app's
 * `show_activity` and `end_activity`; this draws it. Every button on it is an
 * `agenticos://activity/...` link back into the app, so a decision goes through
 * the app's lock and is made by the console, with its own session - the same
 * request its own Approve button makes.
 */
@InvokeArg
class LiveActivityArgs {
    lateinit var id: String
    lateinit var kind: String
    lateinit var title: String
    lateinit var body: String
    lateinit var path: String
    var startedAt: Long? = null
    var approvalId: String? = null
    var approveLabel: String? = null
    var rejectLabel: String? = null
}

@InvokeArg
class EndArgs {
    lateinit var id: String
}

private const val QUIET = "agenticos.activity"
private const val URGENT = "agenticos.decisions"

@TauriPlugin
class LiveActivityPlugin(private val activity: Activity) : Plugin(activity) {
    private val manager = NotificationManagerCompat.from(activity)

    init {
        // A run in progress is quiet - it sits there; an approval is a question
        // somebody is waiting on, and comes up over whatever is on screen.
        val system = activity.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            system.createNotificationChannel(
                NotificationChannel(QUIET, "Agents at work", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Your runs while they are going"
                    setShowBadge(false)
                },
            )
            system.createNotificationChannel(
                NotificationChannel(URGENT, "Waiting for you", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Approvals and questions from your agents"
                },
            )
        }
    }

    private fun link(path: String): PendingIntent {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(path)).setPackage(activity.packageName)
        return PendingIntent.getActivity(
            activity,
            path.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun allowed(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    private var asked = false

    @Command
    fun show(invoke: Invoke) {
        val args = invoke.parseArgs(LiveActivityArgs::class.java)
        if (!allowed()) {
            // Asked when there is first something to show, so the question
            // comes with its reason on screen; once per launch, never nagging.
            if (!asked && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                asked = true
                activity.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2097)
            }
            invoke.resolve()
            return
        }
        val deciding = args.kind == "approval" && args.approvalId != null
        val open = "agenticos://activity/open?path=" + Uri.encode(args.path)
        val builder = NotificationCompat.Builder(activity, if (deciding) URGENT else QUIET)
            .setSmallIcon(R.drawable.ic_stat_agenticos)
            .setContentTitle(args.title)
            .setContentText(args.body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(args.body))
            .setContentIntent(link(open))
            .setOngoing(!deciding)
            .setOnlyAlertOnce(true)
            .setCategory(if (deciding) NotificationCompat.CATEGORY_REMINDER else NotificationCompat.CATEGORY_PROGRESS)
            .setPriority(if (deciding) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_LOW)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
        val started = args.startedAt
        if (started != null) {
            // A run's clock, counting up in the shade without the app awake.
            builder.setWhen(started).setShowWhen(true).setUsesChronometer(true)
        }
        if (args.kind == "run") builder.setProgress(0, 0, true)
        if (deciding) {
            val id = Uri.encode(args.approvalId)
            builder.addAction(0, args.rejectLabel ?: "Reject", link("agenticos://activity/reject?approval=$id"))
            builder.addAction(0, args.approveLabel ?: "Approve", link("agenticos://activity/approve?approval=$id"))
        }
        manager.notify(args.id.hashCode(), builder.build())
        invoke.resolve()
    }

    @Command
    fun end(invoke: Invoke) {
        val args = invoke.parseArgs(EndArgs::class.java)
        manager.cancel(args.id.hashCode())
        invoke.resolve()
    }
}
