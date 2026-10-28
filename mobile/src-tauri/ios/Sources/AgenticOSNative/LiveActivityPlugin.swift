import ActivityKit
import Foundation
import Tauri
import WebKit

struct LiveActivityArgs: Decodable {
  let id: String
  let kind: String
  let title: String
  let body: String
  let path: String
  /// Milliseconds since 1970.
  let startedAt: Double?
  let approvalId: String?
  let approveLabel: String?
  let rejectLabel: String?
}

struct EndActivityArgs: Decodable {
  let id: String
}

/// What the agents are doing, on the lock screen and in the Dynamic Island
/// (#2097): the iOS half of `live.rs`. The console decides what is live; this
/// starts, updates and ends the activities, which the widget extension draws.
/// Their buttons are `agenticos://activity/...` links, so a decision made from
/// the lock screen goes through the app's lock and is made by the console.
class LiveActivityPlugin: Plugin {
  @objc public func show(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(LiveActivityArgs.self)
    guard #available(iOS 16.2, *) else {
      invoke.resolve()
      return
    }
    // Turned off for the app in Settings: nothing to draw, nothing wrong.
    guard ActivityAuthorizationInfo().areActivitiesEnabled else {
      invoke.resolve()
      return
    }
    let state = AgentActivityAttributes.ContentState(
      title: args.title,
      body: args.body,
      startedAt: args.startedAt.map { Date(timeIntervalSince1970: $0 / 1000) },
      approveLabel: args.approveLabel,
      rejectLabel: args.rejectLabel
    )
    // An approval comes up over what is on screen; a run sits there quietly.
    let relevance: Double = args.kind == "approval" ? 100 : 50
    let content = ActivityContent(state: state, staleDate: nil, relevanceScore: relevance)
    Task {
      if let current = Self.activity(args.id) {
        await current.update(content)
      } else {
        let attributes = AgentActivityAttributes(
          key: args.id, kind: args.kind, path: args.path, approvalId: args.approvalId)
        do {
          _ = try Activity.request(attributes: attributes, content: content, pushType: nil)
        } catch {
          invoke.reject("The live activity could not start: \(error.localizedDescription)")
          return
        }
      }
      invoke.resolve()
    }
  }

  @objc public func clear(_ invoke: Invoke) throws {
    guard #available(iOS 16.2, *) else { invoke.resolve(); return }
    Task {
      for activity in Activity<AgentActivityAttributes>.activities {
        await activity.end(nil, dismissalPolicy: .immediate)
      }
      invoke.resolve()
    }
  }

  @objc public func end(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(EndActivityArgs.self)
    guard #available(iOS 16.2, *) else {
      invoke.resolve()
      return
    }
    Task {
      await Self.activity(args.id)?.end(nil, dismissalPolicy: .immediate)
      invoke.resolve()
    }
  }

  @available(iOS 16.2, *)
  private static func activity(_ key: String) -> Activity<AgentActivityAttributes>? {
    Activity<AgentActivityAttributes>.activities.first { $0.attributes.key == key }
  }

  /// Activities left from a run of the app the system ended: the console says
  /// again what is live once it arrives, and nothing it does not say stays up.
  override func load(webview: WKWebView) {
    guard #available(iOS 16.2, *) else { return }
    Task {
      for activity in Activity<AgentActivityAttributes>.activities {
        await activity.end(nil, dismissalPolicy: .immediate)
      }
    }
  }
}

@_cdecl("init_plugin_live_activity")
func initLiveActivityPlugin() -> Plugin {
  LiveActivityPlugin()
}
