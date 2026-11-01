import AppIntents
import SwiftUI
import WidgetKit

/// Control Center, the lock screen's corners and the Action Button (#2097):
/// a new chat, a voice call, dictation - each the `agenticos://activity` link
/// Android's launcher shortcuts open, so a call or dictation started from the
/// lock screen waits for the app's lock.
@available(iOS 18.0, *)
struct NewChatControl: ControlWidget {
  var body: some ControlWidgetConfiguration {
    StaticControlConfiguration(kind: "co.vstorm.agenticos.control.chat") {
      ControlWidgetButton(action: OpenLinkIntent(link: .chat)) {
        Label("control.chat", systemImage: "square.and.pencil")
      }
    }
    .displayName("control.chat")
    .description("control.chat.description")
  }
}

@available(iOS 18.0, *)
struct CallControl: ControlWidget {
  var body: some ControlWidgetConfiguration {
    StaticControlConfiguration(kind: "co.vstorm.agenticos.control.call") {
      ControlWidgetButton(action: OpenLinkIntent(link: .call)) {
        Label("control.call", systemImage: "phone.fill")
      }
    }
    .displayName("control.call")
    .description("control.call.description")
  }
}

@available(iOS 18.0, *)
struct DictateControl: ControlWidget {
  var body: some ControlWidgetConfiguration {
    StaticControlConfiguration(kind: "co.vstorm.agenticos.control.dictate") {
      ControlWidgetButton(action: OpenLinkIntent(link: .dictate)) {
        Label("control.dictate", systemImage: "mic.fill")
      }
    }
    .displayName("control.dictate")
    .description("control.dictate.description")
  }
}

/// Where a control goes.
@available(iOS 18.0, *)
enum ControlLink: String, AppEnum {
  case chat, call, dictate

  static let typeDisplayRepresentation: TypeDisplayRepresentation = "AgenticOS"
  static let caseDisplayRepresentations: [ControlLink: DisplayRepresentation] = [
    .chat: "control.chat", .call: "control.call", .dictate: "control.dictate",
  ]

  var url: URL {
    switch self {
    case .chat: return ActivityLink.newChat
    case .call: return ActivityLink.start("call")
    case .dictate: return ActivityLink.start("dictate")
    }
  }
}

/// Opens the app on a link. Run by the controls only - Shortcuts and Siri
/// have the app's own intents (`Intents.swift`).
@available(iOS 18.0, *)
struct OpenLinkIntent: AppIntent {
  static let title: LocalizedStringResource = "AgenticOS"
  static let isDiscoverable = false

  @Parameter(title: "AgenticOS")
  var link: ControlLink

  init() {}

  init(link: ControlLink) {
    self.link = link
  }

  func perform() async throws -> some IntentResult & OpensIntent {
    .result(opensIntent: OpenURLIntent(link.url))
  }
}
