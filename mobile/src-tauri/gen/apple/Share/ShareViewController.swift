import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// How many items one share may carry, as the attach sheet allows.
private let maxItems = 10
private let maxBytes = 20 * 1024 * 1024

/// "Share → AgenticOS" (#2097): what another app shared - text, a link,
/// photos, files - copied into the App Group's inbox for the console to take
/// into a new message (`ShareTargetPlugin`). The extension holds no session
/// and sends nothing anywhere; the app does, once it is open and unlocked.
final class ShareViewController: UIViewController {
  private let status = ShareStatus()

  override func viewDidLoad() {
    super.viewDidLoad()
    let card = UIHostingController(rootView: ShareCard(status: status) { [weak self] in
      self?.finish()
    })
    addChild(card)
    card.view.backgroundColor = .clear
    card.view.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(card.view)
    NSLayoutConstraint.activate([
      card.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      card.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      card.view.topAnchor.constraint(equalTo: view.topAnchor),
      card.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
    ])
    card.didMove(toParent: self)
    Task { await keep() }
  }

  /// Copy what was shared into a new folder of the inbox, with its manifest.
  private func keep() async {
    guard let inbox = AppGroup.inbox else {
      status.phase = .failed
      return
    }
    let folder = inbox.appendingPathComponent(UUID().uuidString, isDirectory: true)
    let providers = (extensionContext?.inputItems as? [NSExtensionItem] ?? [])
      .flatMap { $0.attachments ?? [] }
    var texts: [String] = []
    var files: [InboxManifest.Entry] = []
    var refused: [String] = []
    do {
      try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
      for (index, provider) in providers.enumerated() {
        if index >= maxItems {
          refused.append(provider.suggestedName ?? "item-\(index + 1)")
          continue
        }
        if let kept = await keepFile(provider, index: index, in: folder) {
          if let entry = kept.entry { files.append(entry) } else { refused.append(kept.name) }
        } else if let text = await loadText(provider) {
          texts.append(text)
        }
      }
      let manifest = InboxManifest(
        text: texts.joined(separator: "\n"), files: files, refused: refused)
      try JSONEncoder().encode(manifest)
        .write(to: folder.appendingPathComponent(InboxManifest.fileName), options: .atomic)
      status.phase = .kept
    } catch {
      try? FileManager.default.removeItem(at: folder)
      status.phase = .failed
    }
  }

  /// A file, photo or video: copied while the provider's copy still exists.
  /// `nil` for something that is not a file; a named refusal for one too large.
  private func keepFile(_ provider: NSItemProvider, index: Int, in folder: URL) async
    -> (name: String, entry: InboxManifest.Entry?)?
  {
    let fileTypes: [UTType] = [.image, .movie, .pdf, .data]
    guard
      let type = fileTypes.first(where: {
        provider.hasItemConformingToTypeIdentifier($0.identifier)
      }),
      !provider.hasItemConformingToTypeIdentifier(UTType.url.identifier)
        || provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier)
    else { return nil }
    return await withCheckedContinuation { done in
      provider.loadFileRepresentation(forTypeIdentifier: type.identifier) { url, _ in
        guard let url else {
          done.resume(returning: (provider.suggestedName ?? "item-\(index + 1)", nil))
          return
        }
        let name = url.lastPathComponent
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        let copy = "\(index)-\(name)"
        guard size <= maxBytes,
          (try? FileManager.default.copyItem(at: url, to: folder.appendingPathComponent(copy)))
            != nil
        else {
          done.resume(returning: (name, nil))
          return
        }
        done.resume(returning: (name, InboxManifest.Entry(file: copy, name: name)))
      }
    }
  }

  /// Text or a link, as words for the message.
  private func loadText(_ provider: NSItemProvider) async -> String? {
    for type in [UTType.url, UTType.plainText] where provider.hasItemConformingToTypeIdentifier(type.identifier) {
      let item = try? await provider.loadItem(forTypeIdentifier: type.identifier)
      if let url = item as? URL { return url.absoluteString }
      if let text = item as? String { return text }
    }
    return nil
  }

  /// Done: open the app on a new chat, where the console takes what was kept.
  ///
  /// An extension may not open its app, so the app is reached the way share
  /// extensions do - through the responder chain to the `UIApplication`. Where
  /// iOS refuses, what was shared waits in the inbox until the app is opened.
  private func finish() {
    if status.phase == .kept {
      var responder: UIResponder? = self
      while let current = responder {
        if let application = current as? UIApplication {
          let selector = NSSelectorFromString("openURL:options:completionHandler:")
          typealias Open = @convention(c) (
            UIApplication, Selector, URL, [UIApplication.OpenExternalURLOptionsKey: Any], Any?
          ) -> Void
          if application.responds(to: selector) {
            let open = unsafeBitCast(application.method(for: selector), to: Open.self)
            open(application, selector, ActivityLink.newChat, [:], nil)
          }
          break
        }
        responder = current.next
      }
    }
    extensionContext?.completeRequest(returningItems: nil)
  }
}

@MainActor
final class ShareStatus: ObservableObject {
  enum Phase { case keeping, kept, failed }
  @Published var phase: Phase = .keeping
}

private struct ShareCard: View {
  @ObservedObject var status: ShareStatus
  let done: () -> Void

  var body: some View {
    VStack {
      Spacer()
      VStack(spacing: 14) {
        switch status.phase {
        case .keeping:
          ProgressView()
          Text("share.keeping").font(.headline)
        case .kept:
          Image(systemName: "checkmark.circle.fill").font(.largeTitle).foregroundStyle(.green)
          Text("share.kept").font(.headline)
          Text("share.kept.detail")
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
        case .failed:
          Image(systemName: "exclamationmark.triangle.fill").font(.largeTitle)
            .foregroundStyle(.red)
          Text("share.failed").font(.headline)
        }
        Button(action: done) {
          Text(status.phase == .kept ? "share.open" : "share.close")
            .font(.body.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 48)
        }
        .buttonStyle(.borderedProminent)
        .tint(.primary)
        .foregroundStyle(Color(uiColor: .systemBackground))
        .disabled(status.phase == .keeping)
      }
      .padding(24)
      .frame(maxWidth: 420)
      .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
      .padding(16)
    }
  }
}
