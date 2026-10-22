import ActivityKit
import SwiftUI
import WidgetKit

/// What an agent is doing, drawn by the system while the app is away
/// (`LiveActivityPlugin`): a run with its clock, or an approval with its two
/// buttons, on the lock screen and in the Dynamic Island. Every tap is an
/// `agenticos://activity` link, so a decision goes through the app's lock and
/// is made by the console with its own session.
struct AgentLiveActivity: Widget {
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: AgentActivityAttributes.self) { context in
      LockScreenActivity(attributes: context.attributes, state: context.state)
        .widgetURL(ActivityLink.open(context.attributes.path))
    } dynamicIsland: { context in
      let attributes = context.attributes
      let state = context.state
      return DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          Blob(waiting: attributes.isApproval)
            .frame(width: 40, height: 40)
            .padding(.leading, 4)
        }
        DynamicIslandExpandedRegion(.trailing) {
          Trailing(attributes: attributes, state: state, compact: false)
            .padding(.trailing, 4)
        }
        DynamicIslandExpandedRegion(.center) {
          VStack(alignment: .leading, spacing: 2) {
            Text(state.title).font(.headline).lineLimit(1)
            if !state.body.isEmpty {
              Text(state.body)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(attributes.isApproval ? 1 : 2)
            }
          }
          .frame(maxWidth: .infinity, alignment: .leading)
        }
        DynamicIslandExpandedRegion(.bottom) {
          if let approvalId = attributes.approvalId, attributes.isApproval {
            Decision(approvalId: approvalId, state: state)
              .padding(.top, 6)
          }
        }
      } compactLeading: {
        Blob(waiting: attributes.isApproval).frame(width: 22, height: 22)
      } compactTrailing: {
        Trailing(attributes: attributes, state: state, compact: true)
      } minimal: {
        Blob(waiting: attributes.isApproval).frame(width: 22, height: 22)
      }
      .widgetURL(ActivityLink.open(attributes.path))
      .keylineTint(attributes.isApproval ? .orange : Blob.skin)
    }
  }
}

/// The right-hand side: a run's clock, counting up without the app awake, or
/// a word saying somebody is waiting.
private struct Trailing: View {
  let attributes: AgentActivityAttributes
  let state: AgentActivityAttributes.ContentState
  let compact: Bool

  var body: some View {
    if attributes.isApproval {
      if compact {
        Image(systemName: "hand.raised.fill").foregroundStyle(.orange)
      } else {
        Text("activity.waiting")
          .font(.caption.weight(.semibold))
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(Color.orange.opacity(0.2), in: Capsule())
          .foregroundStyle(.orange)
      }
    } else if let started = state.startedAt {
      Text(timerInterval: started...Date.distantFuture, countsDown: false)
        .font(compact ? .caption.weight(.semibold) : .title3.weight(.semibold))
        .monospacedDigit()
        .multilineTextAlignment(.trailing)
        .frame(maxWidth: compact ? 52 : 80, alignment: .trailing)
        .foregroundStyle(Blob.skin)
    } else {
      Image(systemName: "ellipsis").foregroundStyle(Blob.skin)
    }
  }
}

/// Reject and Approve, as links back into the app.
private struct Decision: View {
  let approvalId: String
  let state: AgentActivityAttributes.ContentState

  var body: some View {
    HStack(spacing: 8) {
      Link(destination: ActivityLink.decide(approvalId, approve: false)) {
        Text(state.rejectLabel ?? "Reject")
          .font(.subheadline.weight(.semibold))
          .frame(maxWidth: .infinity, minHeight: 40)
          .background(Color.secondary.opacity(0.25), in: Capsule())
      }
      Link(destination: ActivityLink.decide(approvalId, approve: true)) {
        Text(state.approveLabel ?? "Approve")
          .font(.subheadline.weight(.semibold))
          .frame(maxWidth: .infinity, minHeight: 40)
          .background(Color.primary, in: Capsule())
          .foregroundStyle(Color(uiColor: .systemBackground))
      }
    }
  }
}

private struct LockScreenActivity: View {
  let attributes: AgentActivityAttributes
  let state: AgentActivityAttributes.ContentState

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .top, spacing: 12) {
        Blob(waiting: attributes.isApproval).frame(width: 40, height: 40)
        VStack(alignment: .leading, spacing: 3) {
          Text(state.title).font(.headline).lineLimit(2)
          if !state.body.isEmpty {
            Text(state.body)
              .font(.subheadline)
              .foregroundStyle(.secondary)
              .lineLimit(2)
          }
        }
        Spacer(minLength: 0)
        Trailing(attributes: attributes, state: state, compact: false)
      }
      if let approvalId = attributes.approvalId, attributes.isApproval {
        Decision(approvalId: approvalId, state: state)
      }
    }
    .padding(16)
  }
}
