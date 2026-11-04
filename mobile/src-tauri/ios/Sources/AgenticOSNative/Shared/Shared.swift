// Compiled into the app (through the Swift package) and into its widget and
// share extensions (as a source of their Xcode targets): what the three agree
// on - where they keep what they share, and what a live activity is.

import Foundation

#if canImport(ActivityKit)
  import ActivityKit
#endif

/// The App Group the app and its extensions share: the widgets read what the
/// console last counted, the share extension leaves what was shared. A company
/// that signs its own build renames it with the bundle identifier.
public enum AppGroup {
  public static let id = "group.co.vstorm.agenticos"

  public static var defaults: UserDefaults? { UserDefaults(suiteName: id) }

  public static var container: URL? {
    FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: id)
  }

  /// The widget's counts, as `WidgetPlugin` keeps them.
  public enum Glance {
    public static let approvals = "glance.approvals"
    public static let running = "glance.running"
    public static let budgetLeft = "glance.budgetLeft"
    /// Seconds since 1970; absent until the console first counted.
    public static let countedAt = "glance.countedAt"
  }

  /// The agents pinned from the console, newest first: `[{id, name}]`.
  public static let pinnedAgents = "pinnedAgents"
  /// Their faces, `<id>.png`.
  public static var faces: URL? { container?.appendingPathComponent("Faces", isDirectory: true) }
  /// What the share extension left for the console, a folder per share.
  public static var inbox: URL? { container?.appendingPathComponent("Inbox", isDirectory: true) }
}

/// An agent pinned to the phone, as the widgets and Shortcuts list it.
public struct PinnedAgent: Codable, Hashable, Identifiable {
  public let id: String
  public let name: String

  public init(id: String, name: String) {
    self.id = id
    self.name = name
  }

  public static func all() -> [PinnedAgent] {
    guard let raw = AppGroup.defaults?.data(forKey: AppGroup.pinnedAgents) else { return [] }
    return (try? JSONDecoder().decode([PinnedAgent].self, from: raw)) ?? []
  }

  public var faceURL: URL? { AppGroup.faces?.appendingPathComponent("\(id).png") }
}

/// What the share extension leaves in the inbox beside the files it copied,
/// one per share; `ShareTargetPlugin` hands it to the console.
public struct InboxManifest: Codable {
  public struct Entry: Codable {
    /// The copy's name in the share's folder.
    public let file: String
    /// The name it had, shown to the person.
    public let name: String

    public init(file: String, name: String) {
      self.file = file
      self.name = name
    }
  }

  public var text: String
  public var files: [Entry]
  public var refused: [String]

  public init(text: String, files: [Entry], refused: [String]) {
    self.text = text
    self.files = files
    self.refused = refused
  }

  public static let fileName = "share.json"
}

/// The links the app's deep-link handler reads (`activity_link` in the shared
/// Rust crate): every button outside the app comes back through one, so what
/// it asks goes through the app's lock.
public enum ActivityLink {
  public static func open(_ path: String) -> URL {
    var link = URLComponents()
    link.scheme = "agenticos"
    link.host = "activity"
    link.path = "/open"
    link.queryItems = [URLQueryItem(name: "path", value: path)]
    return link.url!
  }

  /// `call` or `dictate`.
  public static func start(_ mode: String) -> URL {
    var link = URLComponents()
    link.scheme = "agenticos"
    link.host = "activity"
    link.path = "/start"
    link.queryItems = [URLQueryItem(name: "mode", value: mode)]
    return link.url!
  }

  public static func chat(with agentId: String) -> URL { open("/chat?with=\(agentId)") }

  public static let newChat = open("/chat")
  public static let approvals = open("/runs?tab=approvals")
  public static let runs = open("/runs")
  public static let dashboard = open("/dashboard")
}

#if canImport(ActivityKit)
  /// One live activity: a run going or an approval waiting. What it is about
  /// stays (`key`, `kind`, the approval); what it says can change.
  @available(iOS 16.1, *)
  public struct AgentActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
      public var title: String
      public var body: String
      /// When the run started, for a clock the system keeps counting.
      public var startedAt: Date?
      public var approveLabel: String?
      public var rejectLabel: String?

      public init(
        title: String, body: String, startedAt: Date?, approveLabel: String?, rejectLabel: String?
      ) {
        self.title = title
        self.body = body
        self.startedAt = startedAt
        self.approveLabel = approveLabel
        self.rejectLabel = rejectLabel
      }
    }

    /// The console's id for it - `run:<id>`, `approval:<id>`.
    public var key: String
    /// `run`, `approval`, `question` or `call`.
    public var kind: String
    /// The console page a tap opens.
    public var path: String
    public var approvalId: String?

    public init(key: String, kind: String, path: String, approvalId: String?) {
      self.key = key
      self.kind = kind
      self.path = path
      self.approvalId = approvalId
    }

    public var isApproval: Bool { kind == "approval" && approvalId != nil }
    /// Somebody is waiting on the person: an approval to decide or a question to answer.
    public var isWaiting: Bool { isApproval || kind == "question" }
    public var isCall: Bool { kind == "call" }
  }
#endif
