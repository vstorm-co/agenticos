import Foundation
import ObjectiveC
import Tauri
import UIKit
import UserNotifications
import WebKit

/// The last device token APNs handed this app, kept so the console can tell
/// the server again on every arrival, as a browser's subscription is.
private let tokenKey = "apns.token"
private let sessionKey = "apns.session"
struct PushSessionArgs: Decodable { let sessionId: String }
/// How long registering waits for APNs to answer with a token.
private let registerTimeout: TimeInterval = 15

struct ApnsStatus: Encodable {
  /// `granted`, `denied` or `undetermined`: whether the person let the app notify.
  let permission: String
  /// Hex, as the server sends to it; absent until registered.
  let token: String?
}

/// Push while the app is closed, on iPhone (#2097): Apple's push service with
/// the organization's own key, which the server holds. This asks the person,
/// registers with APNs and hands the console the device token for the server;
/// a tapped notification opens its console page through the app's lock, the
/// way a live activity's button does.
class ApnsPlugin: Plugin, UNUserNotificationCenterDelegate {
  private static var waiting: [(Result<String, Error>) -> Void] = []

  override func load(webview: WKWebView) {
    UNUserNotificationCenter.current().delegate = self
    Self.installTokenHandlers()
  }

  @objc public func bindSession(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(PushSessionArgs.self)
    if UserDefaults.standard.string(forKey: sessionKey) != args.sessionId {
      UNUserNotificationCenter.current().removeAllDeliveredNotifications()
    }
    UserDefaults.standard.set(args.sessionId, forKey: sessionKey)
    invoke.resolve()
  }

  private func belongsToConnection(_ notification: UNNotification) -> Bool {
    guard let expected = UserDefaults.standard.string(forKey: sessionKey),
      let received = notification.request.content.userInfo["session_id"] as? String else { return false }
    return !expected.isEmpty && received == expected
  }

  @objc public func openSettings(_ invoke: Invoke) throws {
    DispatchQueue.main.async {
      guard let url = URL(string: UIApplication.openSettingsURLString) else {
        invoke.reject("App settings are unavailable.")
        return
      }
      UIApplication.shared.open(url) { opened in
        if opened { invoke.resolve() } else { invoke.reject("App settings could not be opened.") }
      }
    }
  }

  @objc public func status(_ invoke: Invoke) throws {
    UNUserNotificationCenter.current().getNotificationSettings { settings in
      invoke.resolve(
        ApnsStatus(
          permission: Self.permission(settings.authorizationStatus),
          token: UserDefaults.standard.string(forKey: tokenKey)))
    }
  }

  @objc public func register(_ invoke: Invoke) throws {
    UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) {
      granted, error in
      if let error {
        invoke.reject("Notifications could not be turned on: \(error.localizedDescription)")
        return
      }
      guard granted else {
        invoke.resolve(ApnsStatus(permission: "denied", token: nil))
        return
      }
      DispatchQueue.main.async {
        var answered = false
        let answer = { (result: Result<String, Error>) in
          guard !answered else { return }
          answered = true
          switch result {
          case .success(let token):
            invoke.resolve(ApnsStatus(permission: "granted", token: token))
          case .failure(let error):
            invoke.reject("Apple's push service did not register this iPhone: \(error.localizedDescription)")
          }
        }
        Self.waiting.append(answer)
        UIApplication.shared.registerForRemoteNotifications()
        DispatchQueue.main.asyncAfter(deadline: .now() + registerTimeout) {
          answer(.failure(NSError(
            domain: "AgenticOS", code: 1,
            userInfo: [NSLocalizedDescriptionKey: "no answer in time"])))
        }
      }
    }
  }

  @objc public func unregister(_ invoke: Invoke) throws {
    DispatchQueue.main.async {
      UIApplication.shared.unregisterForRemoteNotifications()
      UserDefaults.standard.removeObject(forKey: tokenKey)
      UserDefaults.standard.set("", forKey: sessionKey)
      UNUserNotificationCenter.current().removeAllDeliveredNotifications()
      invoke.resolve()
    }
  }

  private static func permission(_ status: UNAuthorizationStatus) -> String {
    switch status {
    case .authorized, .provisional, .ephemeral: return "granted"
    case .denied: return "denied"
    default: return "undetermined"
    }
  }

  // MARK: Notifications

  /// In front, a notification is still shown: the console's inbox may be a
  /// page away from where the person is.
  func userNotificationCenter(
    _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
    withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    done(belongsToConnection(notification) ? [.banner, .list, .sound] : [])
  }

  /// A tap opens the page the server named - a path of the console, checked
  /// again by the app's link handler.
  func userNotificationCenter(
    _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
    withCompletionHandler done: @escaping () -> Void
  ) {
    guard belongsToConnection(response.notification) else { done(); return }
    let path = response.notification.request.content.userInfo["url"] as? String ?? "/dashboard"
    DispatchQueue.main.async {
      QuickActions.deliver(ActivityLink.open(path))
      done()
    }
  }

  // MARK: The device token

  /// APNs answers through the app delegate, which is Tauri's and has no
  /// such methods: they are added to its class, as the quick actions' are.
  private static var installed = false

  private static func installTokenHandlers() {
    guard !installed, let delegate = UIApplication.shared.delegate else { return }
    installed = true
    let cls: AnyClass = type(of: delegate)
    let registered: @convention(block) (AnyObject, UIApplication, Data) -> Void = { _, _, token in
      let hex = token.map { String(format: "%02x", $0) }.joined()
      UserDefaults.standard.set(hex, forKey: tokenKey)
      finish(.success(hex))
    }
    let failed: @convention(block) (AnyObject, UIApplication, NSError) -> Void = { _, _, error in
      finish(.failure(error))
    }
    class_addMethod(
      cls,
      #selector(UIApplicationDelegate.application(_:didRegisterForRemoteNotificationsWithDeviceToken:)),
      imp_implementationWithBlock(registered), "v@:@@")
    class_addMethod(
      cls,
      #selector(UIApplicationDelegate.application(_:didFailToRegisterForRemoteNotificationsWithError:)),
      imp_implementationWithBlock(failed), "v@:@@")
  }

  private static func finish(_ result: Result<String, Error>) {
    let answers = waiting
    waiting = []
    for answer in answers { answer(result) }
  }
}

@_cdecl("init_plugin_apns")
func initApnsPlugin() -> Plugin {
  ApnsPlugin()
}
