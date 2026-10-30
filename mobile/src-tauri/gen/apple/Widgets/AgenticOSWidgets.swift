import SwiftUI
import WidgetKit

/// Everything the app draws outside itself on iOS (#2097): the home- and
/// lock-screen widgets, the live activities in the Dynamic Island and on the
/// lock screen, and the Control Center buttons. The app keeps what they show
/// in the App Group (`Shared.swift`); none of them reads the server.
@main
struct AgenticOSWidgets: WidgetBundle {
  @WidgetBundleBuilder
  var body: some Widget {
    GlanceWidget()
    PinnedAgentsWidget()
    AgentLiveActivity()
    if #available(iOS 18.0, *) {
      NewChatControl()
      CallControl()
      DictateControl()
    }
  }
}

/// The face on the app's icon, drawn rather than pictured so it stays sharp
/// from the Dynamic Island's 20 points to a widget's 60: a soft square, two
/// eyes. Waiting for the person, it wears a dot.
struct Blob: View {
  var waiting = false

  static let skin = Color(red: 0xBB / 255, green: 0xD1 / 255, blue: 0xFF / 255)
  static let ink = Color(red: 0x0B / 255, green: 0x0F / 255, blue: 0x18 / 255)

  var body: some View {
    GeometryReader { space in
      let side = min(space.size.width, space.size.height)
      ZStack {
        RoundedRectangle(cornerRadius: side * 0.42, style: .continuous)
          .fill(Self.skin)
        HStack(spacing: side * 0.2) {
          Capsule().fill(Self.ink).frame(width: side * 0.09, height: side * 0.26)
          Capsule().fill(Self.ink).frame(width: side * 0.09, height: side * 0.26)
        }
        .offset(y: -side * 0.04)
        if waiting {
          Circle()
            .fill(Color.orange)
            .frame(width: side * 0.32, height: side * 0.32)
            .overlay(Circle().stroke(Color.black, lineWidth: side * 0.06))
            .offset(x: side * 0.38, y: -side * 0.38)
        }
      }
      .frame(width: side, height: side)
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    .aspectRatio(1, contentMode: .fit)
    .accessibilityHidden(true)
  }
}

extension View {
  /// The widget's background, the way the running iOS asks for it.
  @ViewBuilder
  func widgetBackground(_ color: Color) -> some View {
    if #available(iOS 17.0, *) {
      containerBackground(color, for: .widget)
    } else {
      background(color)
    }
  }
}
