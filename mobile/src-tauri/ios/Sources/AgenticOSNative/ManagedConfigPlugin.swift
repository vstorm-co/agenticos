import Foundation
import Tauri

struct ManagedRaw: Encodable {
  let serverUrl: String?
  let serverLocked: Bool?
  let biometricLock: String?
}

/// What the organization's device management set for the app (#2097), as an
/// MDM's managed app configuration (AppConfig) delivers it: the same keys as
/// Android's - `serverUrl`, `serverLocked`, `biometricLock`. Read as given;
/// the rules are the Rust side's.
class ManagedConfigPlugin: Plugin {
  @objc public func read(_ invoke: Invoke) throws {
    let given =
      UserDefaults.standard.dictionary(forKey: "com.apple.configuration.managed") ?? [:]
    invoke.resolve(
      ManagedRaw(
        serverUrl: given["serverUrl"] as? String,
        serverLocked: given["serverLocked"] as? Bool,
        biometricLock: given["biometricLock"] as? String
      ))
  }
}

@_cdecl("init_plugin_managed_config")
func initManagedConfigPlugin() -> Plugin {
  ManagedConfigPlugin()
}
