package co.vstorm.agenticos

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

class MainActivity : TauriActivity() {
  /** The status bar's and the gesture bar's heights, in the page's CSS pixels. */
  @Volatile private var insetTop = 0f
  @Volatile private var insetBottom = 0f
  private var privacyCover: View? = null

  override fun onCreate(savedInstanceState: Bundle?) {
    if (!acceptsPush(intent)) setIntent(Intent(this, MainActivity::class.java))
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      setRecentsScreenshotEnabled(false)
    }
  }

  // The page runs edge to edge, under the status bar and over the gesture bar,
  // and Android's WebView reports no safe area to CSS - so the app measures
  // both and hands them to the page, which keeps that much room (`desktop.css`,
  // the console's appearance script). They differ from one phone to the next.
  override fun onWebViewCreate(webView: WebView) {
    webView.addJavascriptInterface(Insets(), "AgenticOSInsets")
    ViewCompat.setOnApplyWindowInsetsListener(webView) { view, insets ->
      val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
      val density = resources.displayMetrics.density
      insetTop = bars.top / density
      insetBottom = bars.bottom / density
      view.post {
        webView.evaluateJavascript(
          "(function(s){s.setProperty('--shell-inset-top','${insetTop}px');" +
            "s.setProperty('--shell-inset-bottom','${insetBottom}px')})(document.documentElement.style)",
          null,
        )
      }
      insets
    }
  }

  /** Read by the page as it starts: a number, nothing else. */
  inner class Insets {
    @JavascriptInterface fun top(): Float = insetTop

    @JavascriptInterface fun bottom(): Float = insetBottom
  }

  /** Notification history can retain a tap after switching servers. */
  private fun acceptsPush(opened: Intent?): Boolean {
    val data = opened?.data ?: return true
    if (!data.isHierarchical) return true
    val session = data.getQueryParameter("push_session") ?: return true
    return session == PushMessagingService.store(this).getString("session", null)
  }

  override fun onNewIntent(intent: Intent) {
    if (acceptsPush(intent)) super.onNewIntent(intent)
  }

  // The console's session lives in its cookies, and the WebView writes them to
  // disk only now and then. An app the system stops in the background - which
  // it does to any app, at any time - came back signed out. Flushed whenever
  // the app leaves the front, the session survives it.
  override fun onPause() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
      window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }
    // Cover synchronously, before Android captures the task-switcher preview.
    if (privacyCover == null) {
      val cover = View(this).apply { setBackgroundColor(Color.rgb(28, 28, 30)) }
      addContentView(cover, ViewGroup.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT,
      ))
      privacyCover = cover
    }
    CookieManager.getInstance().flush()
    super.onPause()
  }

  override fun onResume() {
    super.onResume()
    privacyCover?.let { (it.parent as? ViewGroup)?.removeView(it) }
    privacyCover = null
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
      window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }
  }
}
