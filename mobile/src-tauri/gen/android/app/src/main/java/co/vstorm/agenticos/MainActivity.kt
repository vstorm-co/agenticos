package co.vstorm.agenticos

import android.os.Bundle
import android.webkit.CookieManager
import androidx.activity.enableEdgeToEdge

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)
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
