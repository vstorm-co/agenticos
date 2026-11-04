import Foundation
import ObjectiveC
import Tauri
import UIKit
import WebKit
import WidgetKit

struct PinArgs: Decodable {
  let id: String
  let name: String
  /// The agent's face, a PNG, base64.
  let icon: String
}

/// How many agents are kept pinned; the long-press menu shows the first four.
private let maxPinned = 8
private let quickActionsShown = 4

/// An agent pinned to the phone (#2097): the iOS half of `pin.rs`. iOS lets no
/// app place an icon on the home screen, so a pinned agent goes where iOS
/// does let it: the "Pinned agents" widget, with its face, the app icon's
/// long-press menu, and Shortcuts and Siri ("Chat with ..."). Each opens a new
/// chat with it through the same `agenticos://activity` link Android's
/// shortcut uses. The answer says `pinned: false` - it is not on the home
/// screen itself until the person adds the widget.
class PinShortcutPlugin: Plugin {
  @objc public func pin(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(PinArgs.self)
    guard let face = Data(base64Encoded: args.icon), UIImage(data: face) != nil else {
      invoke.reject("The agent's face is not an image.")
      return
    }
    guard let defaults = AppGroup.defaults, let faces = AppGroup.faces else {
      invoke.reject("The app group is missing from this build.")
      return
    }
    do {
      try FileManager.default.createDirectory(at: faces, withIntermediateDirectories: true)
      try face.write(to: faces.appendingPathComponent("\(args.id).png"), options: .atomic)
    } catch {
      invoke.reject("The agent's face could not be kept: \(error.localizedDescription)")
      return
    }
    var pinned = PinnedAgent.all().filter { $0.id != args.id }
    pinned.insert(PinnedAgent(id: args.id, name: args.name), at: 0)
    for dropped in pinned.dropFirst(maxPinned) {
      if let url = dropped.faceURL { try? FileManager.default.removeItem(at: url) }
    }
    pinned = Array(pinned.prefix(maxPinned))
    defaults.set(try JSONEncoder().encode(pinned), forKey: AppGroup.pinnedAgents)
    WidgetCenter.shared.reloadAllTimelines()
    DispatchQueue.main.async { Self.showQuickActions(pinned) }
    invoke.resolve(["pinned": false])
  }

  /// The pinned agents in the app icon's long-press menu, below its own
  /// shortcuts (`UIApplicationShortcutItems` in the Info.plist).
  private static func showQuickActions(_ pinned: [PinnedAgent]) {
    UIApplication.shared.shortcutItems = pinned.prefix(quickActionsShown).map { agent in
      UIApplicationShortcutItem(
        type: "co.vstorm.agenticos.agent",
        localizedTitle: agent.name,
        localizedSubtitle: nil,
        icon: UIApplicationShortcutIcon(systemImageName: "bubble.left.and.text.bubble.right"),
        userInfo: ["url": ActivityLink.chat(with: agent.id).absoluteString as NSString]
      )
    }
  }

  override func load(webview: WKWebView) {
    QuickActions.install()
  }
}

/// A long-press menu item chosen: its link goes the way any other
/// `agenticos://` link does, through the app delegate's `openURL`.
///
/// The app delegate is Tauri's (tao's `AppDelegate`), which answers links but
/// not quick actions, so the method is added to its class here - as the
/// desktop shell adds `applicationDockMenu:` to its own. iOS calls it after
/// launching, so it is in place for a cold start from the menu as well.
enum QuickActions {
  private static var installed = false

  static func install() {
    guard !installed, let delegate = UIApplication.shared.delegate else { return }
    installed = true
    let selector = #selector(
      UIApplicationDelegate.application(_:performActionFor:completionHandler:))
    let block:
      @convention(block) (AnyObject, UIApplication, UIApplicationShortcutItem, @escaping (Bool) -> Void)
        -> Void = { _, application, item, done in
          done(open(item, in: application))
        }
    class_addMethod(
      type(of: delegate), selector, imp_implementationWithBlock(block), "v@:@@@?")
  }

  static func open(_ item: UIApplicationShortcutItem, in application: UIApplication) -> Bool {
    let link = (item.userInfo?["url"] as? String).flatMap(URL.init(string:))
      ?? (item.type.hasPrefix("agenticos://") ? URL(string: item.type) : nil)
    guard let link else { return false }
    return deliver(link, in: application)
  }

  /// Hand a link to the app as if the system had opened it.
  @discardableResult
  static func deliver(_ link: URL, in application: UIApplication = .shared) -> Bool {
    application.delegate?.application?(application, open: link, options: [:]) ?? false
  }
}

@_cdecl("init_plugin_pin_shortcut")
func initPinShortcutPlugin() -> Plugin {
  PinShortcutPlugin()
}
