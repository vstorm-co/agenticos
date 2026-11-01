package co.vstorm.agenticos

import android.Manifest
import android.app.Activity
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Size
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.ActivityResult
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import app.tauri.PermissionState
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.Permission
import app.tauri.annotation.PermissionCallback
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import java.io.File

/** How many recent photos the sheet's strip shows. */
private const val RECENT = 24
/** A photo this new is offered on opening the chat, as WhatsApp offers it. */
private const val FRESH_MS = 5 * 60 * 1000L
/** How long the offer stays up before it goes by itself. */
private const val OFFER_MS = 10_000L
private const val STORE = "agenticos.attach"

/**
 * Photos and files into a message, the phone's way (#2097): the composer's
 * "+" opens this sheet - the camera, the photo and file pickers, and a strip
 * of the latest photos to tick - and opening the chat offers a photo taken a
 * moment ago.
 *
 * Drawn here, natively, not by the console: the console is a page of a
 * server, and the gallery stays the phone's. The page is handed only the
 * photos the person taps, in `SharedFiles`' shape.
 */
@TauriPlugin(
    permissions = [
        Permission(strings = [Manifest.permission.READ_MEDIA_IMAGES], alias = "photos"),
        Permission(strings = [Manifest.permission.READ_EXTERNAL_STORAGE], alias = "storage"),
        Permission(strings = [Manifest.permission.CAMERA], alias = "camera"),
    ],
)
class AttachPlugin(private val activity: Activity) : Plugin(activity) {
    private var sheet: BottomSheetDialog? = null
    /** Set while the sheet hands over to a picker or the camera, so its dismissal does not answer. */
    private var handingOver = false
    private var photo: File? = null
    private val main = Handler(Looper.getMainLooper())

    private val photosAlias: String
        get() = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) "photos" else "storage"

    private fun mayReadPhotos(): Boolean {
        val granted = { permission: String ->
            ContextCompat.checkSelfPermission(activity, permission) == android.content.pm.PackageManager.PERMISSION_GRANTED
        }
        return when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE ->
                granted(Manifest.permission.READ_MEDIA_IMAGES) ||
                    granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> granted(Manifest.permission.READ_MEDIA_IMAGES)
            else -> granted(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), activity.resources.displayMetrics).toInt()

    private fun resolve(invoke: Invoke, uris: List<Uri>) {
        invoke.resolve(if (uris.isEmpty()) JSObject() else SharedFiles.collect(activity, uris))
    }

    /** The newest photos, newest first: their URIs and when each was added. */
    private fun recent(limit: Int): List<Pair<Uri, Long>> {
        if (!mayReadPhotos()) return emptyList()
        val found = mutableListOf<Pair<Uri, Long>>()
        activity.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DATE_ADDED),
            null,
            null,
            "${MediaStore.Images.Media.DATE_ADDED} DESC",
        )?.use { cursor ->
            val id = cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val added = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_ADDED)
            while (cursor.moveToNext() && found.size < limit) {
                found.add(
                    ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cursor.getLong(id)) to
                        cursor.getLong(added) * 1000,
                )
            }
        }
        return found
    }

    @Suppress("DEPRECATION")
    private fun thumbnail(uri: Uri): Bitmap? =
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                activity.contentResolver.loadThumbnail(uri, Size(dp(96), dp(96)), null)
            } else {
                MediaStore.Images.Thumbnails.getThumbnail(
                    activity.contentResolver,
                    ContentUris.parseId(uri),
                    MediaStore.Images.Thumbnails.MINI_KIND,
                    null,
                )
            }
        } catch (e: Exception) {
            null
        }

    private fun rounded(view: View, radius: Int, color: Int = Color.TRANSPARENT) {
        view.background = GradientDrawable().apply {
            cornerRadius = dp(radius).toFloat()
            setColor(color)
        }
        view.clipToOutline = true
    }

    // -- the sheet ---------------------------------------------------------

    @Command
    fun openSheet(invoke: Invoke) {
        activity.runOnUiThread { showSheet(invoke) }
    }

    private fun showSheet(invoke: Invoke) {
        sheet?.dismiss()
        handingOver = false
        val dialog = BottomSheetDialog(activity)
        val chosen = linkedSetOf<Uri>()
        val root = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), dp(24))
        }
        val add = MaterialButton(activity).apply {
            text = activity.getString(R.string.attach_add)
            isEnabled = false
            setOnClickListener {
                handingOver = true
                dialog.dismiss()
                resolve(invoke, chosen.toList())
            }
        }

        val actions = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        val ink = ContextCompat.getColor(activity, R.color.widget_text)
        val fill = ContextCompat.getColor(activity, R.color.sheet_tile)
        // A tile per way in, as a messenger's attach sheet has them: the icon on
        // a quiet square, its name under it.
        fun action(label: Int, icon: Int, onClick: () -> Unit) {
            val tile = LinearLayout(activity).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                isClickable = true
                isFocusable = true
                contentDescription = activity.getString(label)
                setOnClickListener { onClick() }
            }
            val glyph = ImageView(activity).apply {
                setImageResource(icon)
                setColorFilter(ink)
                scaleType = ImageView.ScaleType.CENTER
            }
            rounded(glyph, 18, fill)
            tile.addView(glyph, LinearLayout.LayoutParams(dp(60), dp(60)))
            tile.addView(
                TextView(activity).apply {
                    text = activity.getString(label)
                    setTextColor(ink)
                    setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
                    gravity = Gravity.CENTER
                    maxLines = 1
                    setPadding(0, dp(6), 0, 0)
                },
            )
            actions.addView(tile, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        action(R.string.attach_camera, R.drawable.ic_attach_camera) {
            handingOver = true
            dialog.dismiss()
            takePhoto(invoke)
        }
        action(R.string.attach_photos, R.drawable.ic_attach_photos) {
            handingOver = true
            dialog.dismiss()
            pick(invoke, "image/*")
        }
        action(R.string.attach_files, R.drawable.ic_attach_files) {
            handingOver = true
            dialog.dismiss()
            pick(invoke, "*/*")
        }
        root.addView(
            TextView(activity).apply {
                text = activity.getString(R.string.attach_title)
                setTextColor(ContextCompat.getColor(activity, R.color.widget_text))
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
                setTypeface(typeface, android.graphics.Typeface.BOLD)
                setPadding(0, dp(8), 0, dp(16))
            },
        )
        root.addView(actions)

        val strip = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        val photos = recent(RECENT)
        if (photos.isNotEmpty()) {
            for ((uri, _) in photos) {
                val tile = FrameLayout(activity)
                val image = ImageView(activity).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    setImageBitmap(thumbnail(uri))
                    contentDescription = activity.getString(R.string.attach_photo)
                }
                rounded(image, 14)
                val tick = TextView(activity).apply {
                    text = "✓"
                    gravity = Gravity.CENTER
                    setTextColor(Color.WHITE)
                    setTypeface(typeface, android.graphics.Typeface.BOLD)
                    visibility = View.GONE
                }
                rounded(tick, 12, Color.argb(220, 24, 24, 27))
                tile.addView(image, FrameLayout.LayoutParams(dp(88), dp(88)))
                tile.addView(
                    tick,
                    FrameLayout.LayoutParams(dp(24), dp(24), Gravity.TOP or Gravity.END).apply {
                        setMargins(0, dp(6), dp(6), 0)
                    },
                )
                tile.setOnClickListener {
                    if (!chosen.remove(uri)) chosen.add(uri)
                    val picked = uri in chosen
                    tick.visibility = if (picked) View.VISIBLE else View.GONE
                    image.alpha = if (picked) 0.72f else 1f
                    add.isEnabled = chosen.isNotEmpty()
                    add.text = if (chosen.isEmpty()) {
                        activity.getString(R.string.attach_add)
                    } else {
                        activity.resources.getQuantityString(R.plurals.attach_add_n, chosen.size, chosen.size)
                    }
                }
                strip.addView(tile, LinearLayout.LayoutParams(dp(88), dp(88)).apply { marginEnd = dp(8) })
            }
            root.addView(
                HorizontalScrollView(activity).apply {
                    isHorizontalScrollBarEnabled = false
                    addView(strip)
                },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    topMargin = dp(16)
                },
            )
            root.addView(
                add,
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    topMargin = dp(16)
                },
            )
        } else if (!mayReadPhotos()) {
            // Asked here, where the reason is on screen, and nowhere else.
            root.addView(
                MaterialButton(activity, null, com.google.android.material.R.attr.borderlessButtonStyle).apply {
                    text = activity.getString(R.string.attach_allow_recent)
                    setOnClickListener {
                        handingOver = true
                        dialog.dismiss()
                        requestPermissionForAlias(photosAlias, invoke, "photosAllowed")
                    }
                },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    topMargin = dp(12)
                },
            )
        }

        dialog.setContentView(root)
        dialog.setOnDismissListener {
            sheet = null
            if (!handingOver) invoke.resolve(JSObject())
        }
        sheet = dialog
        dialog.show()
    }

    @PermissionCallback
    private fun photosAllowed(invoke: Invoke) {
        // Back to the sheet, now with its strip - or without, if the answer was no.
        activity.runOnUiThread { showSheet(invoke) }
    }

    private fun pick(invoke: Invoke, type: String) {
        val intent = Intent(Intent.ACTION_GET_CONTENT)
            .setType(type)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        startActivityForResult(invoke, Intent.createChooser(intent, null), "picked")
    }

    @ActivityCallback
    private fun picked(invoke: Invoke, result: ActivityResult) {
        val data = result.data
        if (result.resultCode != Activity.RESULT_OK || data == null) {
            invoke.resolve(JSObject())
            return
        }
        val uris = mutableListOf<Uri>()
        val clip = data.clipData
        if (clip != null) {
            for (i in 0 until clip.itemCount) uris.add(clip.getItemAt(i).uri)
        } else {
            data.data?.let { uris.add(it) }
        }
        resolve(invoke, uris)
    }

    private fun takePhoto(invoke: Invoke) {
        // The app declares the camera (the pairing scanner uses it), and a
        // capture intent from an app that declares it but was not granted it
        // is refused - so it is asked for first.
        if (getPermissionState("camera") != PermissionState.GRANTED) {
            requestPermissionForAlias("camera", invoke, "cameraAllowed")
            return
        }
        val file = File(activity.cacheDir, "photo-${System.currentTimeMillis()}.jpg")
        photo = file
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.fileprovider", file)
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            .putExtra(MediaStore.EXTRA_OUTPUT, uri)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivityForResult(invoke, intent, "photographed")
    }

    @PermissionCallback
    private fun cameraAllowed(invoke: Invoke) {
        if (getPermissionState("camera") == PermissionState.GRANTED) {
            takePhoto(invoke)
        } else {
            invoke.resolve(JSObject())
        }
    }

    @ActivityCallback
    private fun photographed(invoke: Invoke, result: ActivityResult) {
        val file = photo
        photo = null
        if (result.resultCode != Activity.RESULT_OK || file == null || !file.exists() || file.length() == 0L) {
            invoke.resolve(JSObject())
            return
        }
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.fileprovider", file)
        resolve(invoke, listOf(uri))
        file.delete()
    }

    // -- the offer of a photo just taken -------------------------------------

    /**
     * Offer the newest photo if it is a few minutes old and has not been
     * offered before: a card above the composer, gone by itself after a few
     * seconds. Answers with the photo if the person adds it, with nothing
     * otherwise - and with nothing at once when there is no such photo, or
     * no permission to look (it is never asked for here).
     */
    @Command
    fun offerRecent(invoke: Invoke) {
        val (uri, added) = recent(1).firstOrNull() ?: return invoke.resolve(JSObject())
        val store = activity.getSharedPreferences(STORE, Context.MODE_PRIVATE)
        if (System.currentTimeMillis() - added > FRESH_MS || store.getString("offered", null) == uri.toString()) {
            invoke.resolve(JSObject())
            return
        }
        store.edit().putString("offered", uri.toString()).apply()
        activity.runOnUiThread { showOffer(invoke, uri) }
    }

    private fun showOffer(invoke: Invoke, uri: Uri) {
        val content = activity.findViewById<FrameLayout>(android.R.id.content)
        var answered = false
        lateinit var card: MaterialCardView
        fun answer(take: Boolean) {
            if (answered) return
            answered = true
            card.animate().alpha(0f).translationY(dp(16).toFloat()).setDuration(160).withEndAction {
                content.removeView(card)
            }
            if (take) resolve(invoke, listOf(uri)) else invoke.resolve(JSObject())
        }
        card = MaterialCardView(activity).apply {
            radius = dp(18).toFloat()
            cardElevation = dp(6).toFloat()
            alpha = 0f
            translationY = dp(16).toFloat()
        }
        val row = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(10), dp(12), dp(10))
        }
        val image = ImageView(activity).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            setImageBitmap(thumbnail(uri))
            contentDescription = activity.getString(R.string.attach_photo)
        }
        rounded(image, 10)
        row.addView(image, LinearLayout.LayoutParams(dp(52), dp(52)))
        row.addView(
            TextView(activity).apply {
                text = activity.getString(R.string.attach_offer)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
                setPadding(dp(12), 0, dp(8), 0)
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        row.addView(
            MaterialButton(activity, null, com.google.android.material.R.attr.borderlessButtonStyle).apply {
                text = activity.getString(R.string.attach_offer_dismiss)
                setOnClickListener { answer(false) }
            },
        )
        row.addView(
            MaterialButton(activity).apply {
                text = activity.getString(R.string.attach_add)
                setOnClickListener { answer(true) }
            },
        )
        card.addView(row)
        content.addView(
            card,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM).apply {
                // Above the composer, whatever the keyboard and the gesture bar take.
                setMargins(dp(12), 0, dp(12), dp(132))
            },
        )
        card.animate().alpha(1f).translationY(0f).setDuration(200)
        main.postDelayed({ answer(false) }, OFFER_MS)
    }
}
