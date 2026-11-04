import AppIntents
import UIKit

/// Siri, Shortcuts, Spotlight and the Action Button (#2097): a voice call,
/// dictation, a new chat, the approvals, a chat with a pinned agent. Each
/// opens the app on the `agenticos://activity` link Android's launcher
/// shortcuts use, so what needs the person - a call, dictation - waits for the
/// app's lock, and the console does the rest.
///
/// They live in the app target, not the Swift package the plugins are in:
/// Xcode reads the intents' metadata from the targets it builds.

/// Hand a link to the app as if the system had opened it.
@MainActor
private func open(_ link: URL) {
  let application = UIApplication.shared
  _ = application.delegate?.application?(application, open: link, options: [:])
}

struct StartCallIntent: AppIntent {
  static let title: LocalizedStringResource = "intent.call"
  static let description = IntentDescription("intent.call.description")
  static let openAppWhenRun = true

  @MainActor
  func perform() async throws -> some IntentResult {
    open(ActivityLink.start("call"))
    return .result()
  }
}

struct DictateIntent: AppIntent {
  static let title: LocalizedStringResource = "intent.dictate"
  static let description = IntentDescription("intent.dictate.description")
  static let openAppWhenRun = true

  @MainActor
  func perform() async throws -> some IntentResult {
    open(ActivityLink.start("dictate"))
    return .result()
  }
}

struct NewChatIntent: AppIntent {
  static let title: LocalizedStringResource = "intent.chat"
  static let description = IntentDescription("intent.chat.description")
  static let openAppWhenRun = true

  @MainActor
  func perform() async throws -> some IntentResult {
    open(ActivityLink.newChat)
    return .result()
  }
}

struct OpenApprovalsIntent: AppIntent {
  static let title: LocalizedStringResource = "intent.approvals"
  static let description = IntentDescription("intent.approvals.description")
  static let openAppWhenRun = true

  @MainActor
  func perform() async throws -> some IntentResult {
    open(ActivityLink.approvals)
    return .result()
  }
}

/// An agent pinned from the console: the agents Shortcuts and Siri offer.
/// Only pinned ones - the app holds no session to list the rest.
struct AgentEntity: AppEntity {
  static let typeDisplayRepresentation: TypeDisplayRepresentation = "intent.agent"
  static let defaultQuery = PinnedAgentQuery()

  let id: String
  let name: String

  var displayRepresentation: DisplayRepresentation {
    let face = PinnedAgent(id: id, name: name).faceURL
    return DisplayRepresentation(
      title: "\(name)", image: face.map { DisplayRepresentation.Image(url: $0) })
  }
}

struct PinnedAgentQuery: EntityQuery {
  private func pinned() -> [AgentEntity] {
    PinnedAgent.all().map { AgentEntity(id: $0.id, name: $0.name) }
  }

  func entities(for identifiers: [String]) async throws -> [AgentEntity] {
    pinned().filter { identifiers.contains($0.id) }
  }

  func suggestedEntities() async throws -> [AgentEntity] { pinned() }
}

struct ChatWithAgentIntent: AppIntent {
  static let title: LocalizedStringResource = "intent.chatWith"
  static let description = IntentDescription("intent.chatWith.description")
  static let openAppWhenRun = true

  @Parameter(title: "intent.agent")
  var agent: AgentEntity

  static var parameterSummary: some ParameterSummary {
    Summary("intent.chatWith.summary \(\.$agent)")
  }

  @MainActor
  func perform() async throws -> some IntentResult {
    open(ActivityLink.chat(with: agent.id))
    return .result()
  }
}

struct AgenticOSShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(
      intent: StartCallIntent(),
      phrases: [
        "Call an agent in \(.applicationName)", "Start a call in \(.applicationName)",
      ],
      shortTitle: "intent.call",
      systemImageName: "phone.fill"
    )
    AppShortcut(
      intent: DictateIntent(),
      phrases: ["Dictate in \(.applicationName)"],
      shortTitle: "intent.dictate",
      systemImageName: "mic.fill"
    )
    AppShortcut(
      intent: NewChatIntent(),
      phrases: ["New chat in \(.applicationName)", "Ask \(.applicationName)"],
      shortTitle: "intent.chat",
      systemImageName: "square.and.pencil"
    )
    AppShortcut(
      intent: OpenApprovalsIntent(),
      phrases: ["Show approvals in \(.applicationName)"],
      shortTitle: "intent.approvals",
      systemImageName: "hand.raised.fill"
    )
    AppShortcut(
      intent: ChatWithAgentIntent(),
      phrases: ["Chat with \(\.$agent) in \(.applicationName)"],
      shortTitle: "intent.chatWith",
      systemImageName: "bubble.left.and.text.bubble.right"
    )
  }
}
