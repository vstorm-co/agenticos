import Foundation
import Tauri

/// "Share → AgenticOS" (#2097): the iOS half of `share.rs`. The share
/// extension copies what was shared into the App Group's inbox, a folder per
/// share; this hands it all to the console once and empties the inbox.
class ShareTargetPlugin: Plugin {
  @objc public func take(_ invoke: Invoke) throws {
    var shared = SharedContent()
    guard let inbox = AppGroup.inbox,
      let shares = try? FileManager.default.contentsOfDirectory(
        at: inbox, includingPropertiesForKeys: [.creationDateKey])
    else {
      invoke.resolve(shared)
      return
    }
    let oldestFirst = shares.sorted {
      let created = { (url: URL) in
        (try? url.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast
      }
      return created($0) < created($1)
    }
    var texts: [String] = []
    for share in oldestFirst {
      defer { try? FileManager.default.removeItem(at: share) }
      guard
        let raw = try? Data(contentsOf: share.appendingPathComponent(InboxManifest.fileName)),
        let manifest = try? JSONDecoder().decode(InboxManifest.self, from: raw)
      else { continue }
      if !manifest.text.isEmpty { texts.append(manifest.text) }
      for entry in manifest.files {
        shared.add(share.appendingPathComponent(entry.file), name: entry.name)
      }
      shared.refused.append(contentsOf: manifest.refused)
    }
    shared.text = texts.joined(separator: "\n")
    invoke.resolve(shared)
  }
}

@_cdecl("init_plugin_share_target")
func initShareTargetPlugin() -> Plugin {
  ShareTargetPlugin()
}
