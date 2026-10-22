package co.vstorm.agenticos

import android.os.Bundle
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

  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
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

  // The console's session lives in its cookies, and the WebView writes them to
  // disk only now and then. An app the system stops in the background - which
  // it does to any app, at any time - came back signed out. Flushed whenever
  // the app leaves the front, the session survives it.
  override fun onPause() {
    CookieManager.getInstance().flush()
    super.onPause()
  }
}
