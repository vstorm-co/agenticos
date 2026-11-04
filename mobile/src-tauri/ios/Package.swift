// swift-tools-version:5.9
// The app's own native half on iOS (#2097): the plugins the console reaches
// through the app - live activities, the widgets' data, sharing, attaching,
// pinned agents, managed configuration and push. `build.rs` compiles it into
// the Rust library, as Tauri's own plugins are; the widget and share
// extensions are Xcode targets of `gen/apple` and share `Shared/` with it.

import PackageDescription

let package = Package(
  name: "agenticos-native",
  platforms: [.iOS(.v16), .macOS(.v13)],
  products: [
    .library(name: "agenticos-native", type: .static, targets: ["AgenticOSNative"])
  ],
  dependencies: [
    .package(name: "Tauri", path: "../.tauri/tauri-api")
  ],
  targets: [
    .target(
      name: "AgenticOSNative",
      dependencies: [.byName(name: "Tauri")],
      path: "Sources/AgenticOSNative"
    )
  ]
)
