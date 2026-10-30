import Tauri
import UIKit
import WebKit

/// Hide account content synchronously before UIKit takes an app-switcher snapshot.
/// This also protects previews when the user has chosen not to require biometrics.
class AppPrivacyPlugin: Plugin {
  private weak var webview: WKWebView?
  private var cover: UIView?

  override func load(webview: WKWebView) {
    self.webview = webview
    NotificationCenter.default.addObserver(
      self, selector: #selector(hidePreview),
      name: UIApplication.willResignActiveNotification, object: nil)
    NotificationCenter.default.addObserver(
      self, selector: #selector(restorePreview),
      name: UIApplication.didBecomeActiveNotification, object: nil)
  }

  @objc private func hidePreview() {
    guard cover == nil, let window = webview?.window else { return }
    let view = UIView(frame: window.bounds)
    view.backgroundColor = .systemBackground
    view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    window.addSubview(view)
    cover = view
  }

  @objc private func restorePreview() {
    cover?.removeFromSuperview()
    cover = nil
  }

  deinit {
    NotificationCenter.default.removeObserver(self)
  }
}

@_cdecl("init_plugin_app_privacy")
func initAppPrivacyPlugin() -> Plugin {
  AppPrivacyPlugin()
}
