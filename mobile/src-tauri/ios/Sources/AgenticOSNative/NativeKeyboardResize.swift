import UIKit
import WebKit

/// One owner of keyboard layout: resize the native frame before WebKit pans it.
/// DOM scroll containers remain enabled; only WebKit's duplicate keyboard
/// notifications are detached, as in Capacitor's native resize mode.
final class NativeKeyboardResize: NSObject {
  private weak var webview: WKWebView?
  private var keyboardInScreen = CGRect.null
  private let margins: UIEdgeInsets

  init(webview: WKWebView) {
    self.webview = webview
    let bounds = webview.superview?.bounds ?? webview.frame
    margins = UIEdgeInsets(
      top: webview.frame.minY - bounds.minY,
      left: webview.frame.minX - bounds.minX,
      bottom: bounds.maxY - webview.frame.maxY,
      right: bounds.maxX - webview.frame.maxX)
    super.init()
    let center = NotificationCenter.default
    for name in [UIResponder.keyboardWillShowNotification, UIResponder.keyboardWillHideNotification,
      UIResponder.keyboardWillChangeFrameNotification, UIResponder.keyboardDidChangeFrameNotification]
    {
      center.removeObserver(webview, name: name, object: nil)
    }
    center.addObserver(
      self, selector: #selector(keyboardChanged(_:)),
      name: UIResponder.keyboardWillChangeFrameNotification, object: nil)
    center.addObserver(
      self, selector: #selector(keyboardHidden(_:)),
      name: UIResponder.keyboardWillHideNotification, object: nil)
    center.addObserver(
      self, selector: #selector(restoreLayout),
      name: UIApplication.didBecomeActiveNotification, object: nil)
    center.addObserver(
      self, selector: #selector(rotated),
      name: UIDevice.orientationDidChangeNotification, object: nil)
  }

  @objc private func keyboardChanged(_ notification: Notification) {
    guard let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else {
      return
    }
    keyboardInScreen = frame
    resize(notification)
  }

  @objc private func keyboardHidden(_ notification: Notification) {
    keyboardInScreen = .null
    resize(notification)
  }

  @objc private func restoreLayout() {
    DispatchQueue.main.async { [weak self] in
      guard let self, let host = self.webview?.superview,
        let window = self.webview?.window else { return }
      host.layoutIfNeeded()
      let frame = host.keyboardLayoutGuide.layoutFrame
      self.keyboardInScreen = frame.height > host.safeAreaInsets.bottom
        ? host.convert(frame, to: window.screen.coordinateSpace) : .null
      self.resize(nil)
    }
  }

  @objc private func rotated() { restoreLayout() }

  private func resize(_ notification: Notification?) {
    guard let webview, let host = webview.superview, let window = webview.window else { return }
    let base = host.bounds.inset(by: margins)
    let keyboard = keyboardInScreen.isNull
      ? CGRect.null : host.convert(keyboardInScreen, from: window.screen.coordinateSpace)
    let target = keyboardAdjustedFrame(base: base, keyboard: keyboard)
    let changes = {
      webview.frame = target
      webview.scrollView.contentInset = .zero
      webview.scrollView.scrollIndicatorInsets = .zero
      webview.scrollView.setContentOffset(.zero, animated: false)
    }
    let duration = notification?.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? 0
    let curve = notification?.userInfo?[UIResponder.keyboardAnimationCurveUserInfoKey] as? UInt ?? 0
    UIView.animate(
      withDuration: duration, delay: 0,
      options: [UIView.AnimationOptions(rawValue: curve << 16), .beginFromCurrentState, .allowUserInteraction],
      animations: changes)
  }

  deinit { NotificationCenter.default.removeObserver(self) }
}
