import Foundation
import Tauri
import WidgetKit

struct GlanceArgs: Decodable {
  let approvals: Int
  let running: Int
  /// Percent of the organization's monthly cap left; absent with no cap to read.
  let budget_left: Int?
}

/// The home-screen and lock-screen widgets' counts (#2097): the iOS half of
/// `widget.rs`. The console sends what it just counted; it is kept in the App
/// Group, with the time, for the widget extension to draw.
class WidgetPlugin: Plugin {
  @objc public func clear(_ invoke: Invoke) throws {
    guard let defaults = AppGroup.defaults else {
      invoke.reject("The app group is missing from this build.")
      return
    }
    for key in [AppGroup.Glance.approvals, AppGroup.Glance.running, AppGroup.Glance.budgetLeft, AppGroup.Glance.countedAt, AppGroup.pinnedAgents] {
      defaults.removeObject(forKey: key)
    }
    if let faces = AppGroup.faces, FileManager.default.fileExists(atPath: faces.path) {
      try FileManager.default.removeItem(at: faces)
    }
    WidgetCenter.shared.reloadAllTimelines()
    invoke.resolve()
  }

  @objc public func update(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(GlanceArgs.self)
    guard let defaults = AppGroup.defaults else {
      invoke.reject("The app group is missing from this build.")
      return
    }
    defaults.set(args.approvals, forKey: AppGroup.Glance.approvals)
    defaults.set(args.running, forKey: AppGroup.Glance.running)
    defaults.set(args.budget_left ?? -1, forKey: AppGroup.Glance.budgetLeft)
    defaults.set(Date().timeIntervalSince1970, forKey: AppGroup.Glance.countedAt)
    WidgetCenter.shared.reloadAllTimelines()
    invoke.resolve()
  }
}

@_cdecl("init_plugin_widget")
func initWidgetPlugin() -> Plugin {
  WidgetPlugin()
}
