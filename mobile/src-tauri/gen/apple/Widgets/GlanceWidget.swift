import SwiftUI
import WidgetKit

/// Approvals waiting for the person and their runs in flight, as the console
/// last counted them (`WidgetPlugin`). Nothing here reads the server - the app
/// holds no session of its own - so the time they were counted is shown, and
/// an old number says it is old.
struct GlanceEntry: TimelineEntry {
  let date: Date
  let approvals: Int
  let running: Int
  /// Percent of this month's cap left; absent with no cap.
  let budgetLeft: Int?
  /// Absent until the console first counted.
  let countedAt: Date?

  static func read() -> GlanceEntry {
    let defaults = AppGroup.defaults
    let counted = defaults?.double(forKey: AppGroup.Glance.countedAt) ?? 0
    let budget = defaults?.object(forKey: AppGroup.Glance.budgetLeft) as? Int ?? -1
    return GlanceEntry(
      date: Date(),
      approvals: defaults?.integer(forKey: AppGroup.Glance.approvals) ?? 0,
      running: defaults?.integer(forKey: AppGroup.Glance.running) ?? 0,
      budgetLeft: budget >= 0 ? budget : nil,
      countedAt: counted > 0 ? Date(timeIntervalSince1970: counted) : nil
    )
  }

  static let preview = GlanceEntry(
    date: Date(), approvals: 2, running: 1, budgetLeft: 64, countedAt: Date())
}

struct GlanceProvider: TimelineProvider {
  func placeholder(in context: Context) -> GlanceEntry { .preview }

  func getSnapshot(in context: Context, completion: @escaping (GlanceEntry) -> Void) {
    completion(context.isPreview ? .preview : .read())
  }

  // The app reloads the timeline whenever the console counts again.
  func getTimeline(in context: Context, completion: @escaping (Timeline<GlanceEntry>) -> Void) {
    completion(Timeline(entries: [.read()], policy: .never))
  }
}

struct GlanceWidget: Widget {
  var body: some WidgetConfiguration {
    StaticConfiguration(kind: "co.vstorm.agenticos.glance", provider: GlanceProvider()) { entry in
      GlanceView(entry: entry)
    }
    .configurationDisplayName("AgenticOS")
    .description("glance.description")
    .supportedFamilies([
      .systemSmall, .systemMedium, .accessoryCircular, .accessoryRectangular, .accessoryInline,
    ])
  }
}

struct GlanceView: View {
  let entry: GlanceEntry
  @Environment(\.widgetFamily) private var family

  private var known: Bool { entry.countedAt != nil }
  private var waiting: Bool { entry.approvals > 0 }

  var body: some View {
    switch family {
    case .accessoryCircular:
      ZStack {
        AccessoryWidgetBackground()
        VStack(spacing: 0) {
          Image(systemName: "hand.raised.fill").font(.caption)
          Text(known ? "\(entry.approvals)" : "–").font(.title3.weight(.semibold))
        }
      }
      .widgetURL(ActivityLink.approvals)
      .widgetBackground(.clear)
    case .accessoryRectangular:
      VStack(alignment: .leading, spacing: 2) {
        Text("AgenticOS").font(.headline)
        if known {
          Text("glance.waiting.count \(entry.approvals)")
          Text("glance.running.count \(entry.running)")
        } else {
          Text("glance.never")
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      .widgetURL(waiting ? ActivityLink.approvals : ActivityLink.dashboard)
      .widgetBackground(.clear)
    case .accessoryInline:
      Group {
        if known {
          Text("glance.inline \(entry.approvals) \(entry.running)")
        } else {
          Text("glance.never")
        }
      }
      .widgetURL(ActivityLink.approvals)
      .widgetBackground(.clear)
    case .systemMedium:
      VStack(alignment: .leading, spacing: 12) {
        header
        HStack(spacing: 10) {
          Link(destination: ActivityLink.approvals) {
            tile(entry.approvals, label: "glance.waiting", tint: waiting)
          }
          Link(destination: ActivityLink.runs) {
            tile(entry.running, label: "glance.running", tint: false)
          }
          if let left = entry.budgetLeft {
            Link(destination: ActivityLink.dashboard) {
              budgetTile(left)
            }
          }
        }
      }
      .widgetURL(ActivityLink.dashboard)
      .widgetBackground(Color(uiColor: .systemBackground))
    default:
      VStack(alignment: .leading, spacing: 8) {
        header
        Spacer(minLength: 0)
        count(entry.approvals, label: "glance.waiting", tint: waiting)
        count(entry.running, label: "glance.running", tint: false)
      }
      .widgetURL(waiting ? ActivityLink.approvals : ActivityLink.dashboard)
      .widgetBackground(Color(uiColor: .systemBackground))
    }
  }

  private var header: some View {
    HStack(spacing: 6) {
      Blob(waiting: waiting).frame(width: 22, height: 22)
      Spacer(minLength: 0)
      if let counted = entry.countedAt {
        Text(counted, style: .time)
          .font(.caption2)
          .foregroundStyle(.secondary)
      } else {
        Text("glance.never").font(.caption2).foregroundStyle(.secondary)
      }
    }
  }

  private func number(_ value: Int) -> String { known ? "\(value)" : "–" }

  private func count(_ value: Int, label: LocalizedStringKey, tint: Bool) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 6) {
      Text(number(value))
        .font(.system(.title2, design: .rounded).weight(.semibold))
        .monospacedDigit()
        .foregroundStyle(tint ? Color.orange : Color.primary)
      Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1)
    }
  }

  private func budgetTile(_ left: Int) -> some View {
    VStack(alignment: .leading, spacing: 2) {
      Text("\(left)%")
        .font(.system(.largeTitle, design: .rounded).weight(.semibold))
        .monospacedDigit()
        .foregroundStyle(left <= 10 ? Color.orange : Color.primary)
      Text("glance.budgetLeft").font(.footnote).foregroundStyle(.secondary).lineLimit(1)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(12)
    .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
  }

  private func tile(_ value: Int, label: LocalizedStringKey, tint: Bool) -> some View {
    VStack(alignment: .leading, spacing: 2) {
      Text(number(value))
        .font(.system(.largeTitle, design: .rounded).weight(.semibold))
        .monospacedDigit()
        .foregroundStyle(tint ? Color.orange : Color.primary)
      Text(label).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(12)
    .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
  }
}
