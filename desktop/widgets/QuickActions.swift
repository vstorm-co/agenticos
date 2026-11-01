import SwiftUI
import WidgetKit

struct LauncherEntry: TimelineEntry { let date: Date }
struct LauncherProvider: TimelineProvider {
  func placeholder(in context: Context) -> LauncherEntry { LauncherEntry(date: .now) }
  func getSnapshot(in context: Context, completion: @escaping (LauncherEntry) -> Void) { completion(LauncherEntry(date: .now)) }
  func getTimeline(in context: Context, completion: @escaping (Timeline<LauncherEntry>) -> Void) {
    completion(Timeline(entries: [LauncherEntry(date: .now)], policy: .never))
  }
}
struct LauncherView: View {
  @Environment(\.widgetFamily) private var family
  private let quickAsk = URL(string: "agenticos://widget/quick-ask")!
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(spacing: 8) {
        Image("WidgetMark").resizable().frame(width: 28, height: 28)
        Text("AgenticOS").font(.headline)
      }
      if family == .systemSmall {
        Spacer(minLength: 0)
        Label("widget.ask", systemImage: "bubble.left.and.text.bubble.right")
          .font(.title3.weight(.semibold))
        Text("widget.subtitle").font(.caption).foregroundStyle(.secondary)
      } else {
        HStack(spacing: 10) {
          action("widget.ask", "bubble.left.and.text.bubble.right", "quick-ask")
          action("widget.chat", "square.and.pencil", "chat")
          action("widget.inbox", "tray", "inbox")
          action("widget.activity", "waveform.path", "activity")
        }
      }
    }
    .widgetURL(quickAsk)
    .containerBackground(.quaternary, for: .widget)
  }
  private func action(_ title: LocalizedStringKey, _ symbol: String, _ path: String) -> some View {
    Link(destination: URL(string: "agenticos://widget/\(path)")!) {
      VStack(spacing: 7) {
        Image(systemName: symbol).font(.title3)
        Text(title).font(.caption2.weight(.medium)).lineLimit(1).minimumScaleFactor(0.8)
      }
      .frame(maxWidth: .infinity, minHeight: 66)
      .background(.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
    }
    .buttonStyle(.plain)
  }
}
struct QuickActionsWidget: Widget {
  let kind = "co.vstorm.agenticos.widgets.quick-actions"
  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: LauncherProvider()) { _ in LauncherView() }
      .configurationDisplayName("widget.name")
      .description("widget.description")
      .supportedFamilies([.systemSmall, .systemMedium])
  }
}
@main
struct AgenticOSWidgets: WidgetBundle {
  var body: some Widget { QuickActionsWidget() }
}
