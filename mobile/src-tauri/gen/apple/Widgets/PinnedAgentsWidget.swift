import SwiftUI
import UIKit
import WidgetKit

/// The agents pinned from the console (`PinShortcutPlugin`), with their faces:
/// iOS's answer to Android's pinned home-screen shortcut. A tap on a face is a
/// new chat with that agent.
struct PinnedEntry: TimelineEntry {
  struct Agent: Identifiable {
    let id: String
    let name: String
    let face: UIImage?
  }

  let date: Date
  let agents: [Agent]

  static func read() -> PinnedEntry {
    let agents = PinnedAgent.all().map { agent in
      Agent(
        id: agent.id, name: agent.name,
        face: agent.faceURL.flatMap { UIImage(contentsOfFile: $0.path) })
    }
    return PinnedEntry(date: Date(), agents: agents)
  }

  static let preview = PinnedEntry(
    date: Date(),
    agents: ["Support", "Research", "Sales", "Legal"].enumerated().map {
      Agent(id: "\($0.offset)", name: $0.element, face: nil)
    })
}

struct PinnedProvider: TimelineProvider {
  func placeholder(in context: Context) -> PinnedEntry { .preview }

  func getSnapshot(in context: Context, completion: @escaping (PinnedEntry) -> Void) {
    let pinned = PinnedEntry.read()
    completion(context.isPreview && pinned.agents.isEmpty ? .preview : pinned)
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<PinnedEntry>) -> Void) {
    completion(Timeline(entries: [.read()], policy: .never))
  }
}

struct PinnedAgentsWidget: Widget {
  var body: some WidgetConfiguration {
    StaticConfiguration(kind: "co.vstorm.agenticos.pinned", provider: PinnedProvider()) { entry in
      PinnedView(entry: entry)
    }
    .configurationDisplayName("pinned.name")
    .description("pinned.description")
    .supportedFamilies([.systemSmall, .systemMedium, .accessoryCircular])
  }
}

struct PinnedView: View {
  let entry: PinnedEntry
  @Environment(\.widgetFamily) private var family

  var body: some View {
    Group {
      if entry.agents.isEmpty {
        empty
      } else {
        switch family {
        case .accessoryCircular:
          face(entry.agents[0], size: 60).clipShape(Circle())
            .widgetURL(ActivityLink.chat(with: entry.agents[0].id))
        case .systemMedium:
          HStack(alignment: .top, spacing: 8) {
            ForEach(entry.agents.prefix(4)) { agent in
              Link(destination: ActivityLink.chat(with: agent.id)) { cell(agent) }
            }
            ForEach(entry.agents.count..<max(entry.agents.count, 4), id: \.self) { _ in
              Color.clear.frame(maxWidth: .infinity)
            }
          }
          .widgetURL(ActivityLink.chat(with: entry.agents[0].id))
        default:
          let agent = entry.agents[0]
          VStack(alignment: .leading, spacing: 8) {
            face(agent, size: 56)
            Spacer(minLength: 0)
            Text(agent.name).font(.headline).lineLimit(2)
            Label("pinned.newChat", systemImage: "square.and.pencil")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
          .frame(maxWidth: .infinity, alignment: .leading)
          .widgetURL(ActivityLink.chat(with: agent.id))
        }
      }
    }
    .widgetBackground(
      family == .accessoryCircular ? .clear : Color(uiColor: .systemBackground))
  }

  private var empty: some View {
    VStack(alignment: .leading, spacing: 8) {
      Blob().frame(width: 32, height: 32)
      Spacer(minLength: 0)
      Text("pinned.empty")
        .font(.footnote)
        .foregroundStyle(.secondary)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .widgetURL(ActivityLink.open("/agents"))
  }

  private func cell(_ agent: PinnedEntry.Agent) -> some View {
    VStack(spacing: 6) {
      face(agent, size: 52)
      Text(agent.name)
        .font(.caption)
        .lineLimit(1)
        .foregroundStyle(.primary)
    }
    .frame(maxWidth: .infinity)
  }

  @ViewBuilder
  private func face(_ agent: PinnedEntry.Agent, size: CGFloat) -> some View {
    if let face = agent.face {
      Image(uiImage: face)
        .resizable()
        .scaledToFill()
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.3, style: .continuous))
        .accessibilityLabel(agent.name)
    } else {
      Blob().frame(width: size, height: size).accessibilityLabel(agent.name)
    }
  }
}
