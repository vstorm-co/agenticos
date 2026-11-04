package co.vstorm.agenticos

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/**
 * "Ask AgenticOS" in Quick Settings (#2097): one tap from anywhere to the chat,
 * through the same link the launcher's Chat shortcut opens.
 */
class AskTileService : TileService() {
    // A tile starts out "unavailable" until its service says otherwise; this
    // one is a button, always ready, never on or off.
    override fun onStartListening() {
        qsTile?.apply {
            state = Tile.STATE_INACTIVE
            updateTile()
        }
    }

    override fun onClick() {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("agenticos://activity/open?path=%2Fchat"))
            .setPackage(packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE),
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}
