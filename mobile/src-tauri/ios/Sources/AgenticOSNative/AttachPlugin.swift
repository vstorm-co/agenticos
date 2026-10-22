import Foundation
import Photos
import PhotosUI
import Tauri
import UIKit
import UniformTypeIdentifiers

struct AttachArgs: Decodable {
  /// `camera`, `photos` or `files`: the tile the person tapped in the
  /// console's sheet.
  let source: String?
}

/// How many photos and files one pick may bring.
private let maxPicked = 10
/// A photo this new is offered on opening the chat, as WhatsApp offers it.
private let freshFor: TimeInterval = 5 * 60
/// How long the offer stays up before it goes by itself.
private let offerFor: TimeInterval = 10
private let offeredKey = "attach.offered"

/// Photos and files into a message, the phone's way (#2097): the iOS half of
/// the attach commands in `share.rs`. The console's sheet names where a file
/// comes from, and this opens the camera, the photo picker or Files there;
/// opening the chat offers a photo taken a moment ago. The console is handed
/// only what the person picked, in `SharedContent`'s shape.
///
/// The photo picker needs no permission: it runs outside the app, and the
/// app sees only the photos picked. Reading the library - for the offer - is
/// asked for the first time the person picks photos, so the question comes
/// with the reason on screen.
class AttachPlugin: Plugin, PHPickerViewControllerDelegate, UIImagePickerControllerDelegate,
  UINavigationControllerDelegate, UIDocumentPickerDelegate
{
  /// The pick waiting for the person; one at a time.
  private var pending: Invoke?
  private var offer: UIView?

  private var presenter: UIViewController? {
    var top = manager.viewController
    while let shown = top?.presentedViewController { top = shown }
    return top
  }

  @objc public func openSheet(_ invoke: Invoke) throws {
    let args = try invoke.parseArgs(AttachArgs.self)
    DispatchQueue.main.async {
      self.answer(SharedContent())
      self.pending = invoke
      switch args.source {
      case "camera" where UIImagePickerController.isSourceTypeAvailable(.camera):
        let camera = UIImagePickerController()
        camera.sourceType = .camera
        camera.delegate = self
        self.presenter?.present(camera, animated: true)
      case "files":
        let files = UIDocumentPickerViewController(forOpeningContentTypes: [.item], asCopy: true)
        files.allowsMultipleSelection = true
        files.delegate = self
        self.presenter?.present(files, animated: true)
      default:
        // The photos - and the camera where there is none, as in the simulator.
        self.askToReadPhotosOnce()
        var configuration = PHPickerConfiguration()
        configuration.selectionLimit = maxPicked
        configuration.filter = .any(of: [.images, .videos])
        // HEIC and HEVC come as JPEG and H.264: what the server and the model read.
        configuration.preferredAssetRepresentationMode = .compatible
        let picker = PHPickerViewController(configuration: configuration)
        picker.delegate = self
        self.presenter?.present(picker, animated: true)
      }
    }
  }

  private func answer(_ content: SharedContent) {
    pending?.resolve(content)
    pending = nil
  }

  private func askToReadPhotosOnce() {
    guard PHPhotoLibrary.authorizationStatus(for: .readWrite) == .notDetermined else { return }
    PHPhotoLibrary.requestAuthorization(for: .readWrite) { _ in }
  }

  // MARK: The photo picker

  func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
    picker.dismiss(animated: true)
    let group = DispatchGroup()
    let lock = NSLock()
    var picked = SharedContent()
    for (index, result) in results.enumerated() {
      let provider = result.itemProvider
      let type: UTType = provider.hasItemConformingToTypeIdentifier(UTType.movie.identifier)
        ? .movie : .jpeg
      group.enter()
      provider.loadFileRepresentation(forTypeIdentifier: type.identifier) { url, _ in
        defer { group.leave() }
        let base = provider.suggestedName ?? "photo-\(index + 1)"
        let name = "\(base).\(url?.pathExtension ?? type.preferredFilenameExtension ?? "jpg")"
        lock.lock()
        defer { lock.unlock() }
        // The file is gone when this returns, so it is read now.
        if let url { picked.add(url, name: name) } else { picked.refused.append(name) }
      }
    }
    group.notify(queue: .main) { self.answer(picked) }
  }

  // MARK: The camera

  func imagePickerController(
    _ picker: UIImagePickerController,
    didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
  ) {
    picker.dismiss(animated: true)
    var taken = SharedContent()
    if let photo = info[.originalImage] as? UIImage, let jpeg = photo.jpegData(compressionQuality: 0.85) {
      taken.add(jpeg, name: "photo-\(Self.stamp()).jpg", type: .jpeg)
    }
    answer(taken)
  }

  func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
    picker.dismiss(animated: true)
    answer(SharedContent())
  }

  // MARK: Files

  func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
    var picked = SharedContent()
    for url in urls.prefix(maxPicked) { picked.add(url) }
    for url in urls.dropFirst(maxPicked) { picked.refused.append(url.lastPathComponent) }
    answer(picked)
  }

  func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
    answer(SharedContent())
  }

  // MARK: The offer of a photo just taken

  /// The newest photo, if it is a few minutes old and was not offered
  /// before: a card above the composer, gone by itself after a few seconds.
  /// Only where the person let the app read the photos; never asked from here.
  @objc public func offerRecent(_ invoke: Invoke) throws {
    let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    guard status == .authorized || status == .limited else {
      invoke.resolve(SharedContent())
      return
    }
    let newest = PHFetchOptions()
    newest.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
    newest.fetchLimit = 1
    guard let asset = PHAsset.fetchAssets(with: .image, options: newest).firstObject,
      let created = asset.creationDate, Date().timeIntervalSince(created) < freshFor,
      UserDefaults.standard.string(forKey: offeredKey) != asset.localIdentifier
    else {
      invoke.resolve(SharedContent())
      return
    }
    UserDefaults.standard.set(asset.localIdentifier, forKey: offeredKey)
    let options = PHImageRequestOptions()
    options.isNetworkAccessAllowed = true
    options.deliveryMode = .highQualityFormat
    PHImageManager.default().requestImage(
      for: asset, targetSize: CGSize(width: 2048, height: 2048), contentMode: .aspectFit,
      options: options
    ) { image, _ in
      guard let image else {
        invoke.resolve(SharedContent())
        return
      }
      DispatchQueue.main.async { self.showOffer(image, invoke: invoke) }
    }
  }

  private func showOffer(_ image: UIImage, invoke: Invoke) {
    guard offer == nil, let host = manager.viewController?.view else {
      invoke.resolve(SharedContent())
      return
    }
    var answered = false
    let card = OfferCard(image: image) { [weak self] add in
      guard !answered else { return }
      answered = true
      var taken = SharedContent()
      if add, let jpeg = image.jpegData(compressionQuality: 0.85) {
        taken.add(jpeg, name: "photo-\(Self.stamp()).jpg", type: .jpeg)
      }
      invoke.resolve(taken)
      UIView.animate(withDuration: 0.2, animations: { self?.offer?.alpha = 0 }) { _ in
        self?.offer?.removeFromSuperview()
        self?.offer = nil
      }
    }
    offer = card
    card.place(in: host)
    DispatchQueue.main.asyncAfter(deadline: .now() + offerFor) { card.decide(false) }
  }

  private static func stamp() -> String {
    let format = DateFormatter()
    format.dateFormat = "yyyyMMdd-HHmmss"
    return format.string(from: Date())
  }
}

/// The offer: the photo, a line, Not now and Add - above the composer, where
/// the thumb is.
private final class OfferCard: UIVisualEffectView {
  private let onDecide: (Bool) -> Void

  init(image: UIImage, onDecide: @escaping (Bool) -> Void) {
    self.onDecide = onDecide
    super.init(effect: UIBlurEffect(style: .systemMaterial))
    layer.cornerRadius = 20
    layer.cornerCurve = .continuous
    clipsToBounds = true

    let thumbnail = UIImageView(image: image)
    thumbnail.contentMode = .scaleAspectFill
    thumbnail.clipsToBounds = true
    thumbnail.layer.cornerRadius = 12
    thumbnail.isAccessibilityElement = true
    thumbnail.accessibilityLabel = Words.photo
    thumbnail.widthAnchor.constraint(equalToConstant: 56).isActive = true
    thumbnail.heightAnchor.constraint(equalToConstant: 56).isActive = true

    let line = UILabel()
    line.text = Words.offer
    line.font = .preferredFont(forTextStyle: .subheadline)
    line.numberOfLines = 2

    var dismiss = UIButton.Configuration.gray()
    dismiss.title = Words.notNow
    dismiss.cornerStyle = .capsule
    var add = UIButton.Configuration.filled()
    add.title = Words.add
    add.cornerStyle = .capsule
    add.baseBackgroundColor = .label
    add.baseForegroundColor = .systemBackground
    let buttons = UIStackView(arrangedSubviews: [
      UIButton(configuration: dismiss, primaryAction: UIAction { [weak self] _ in self?.decide(false) }),
      UIButton(configuration: add, primaryAction: UIAction { [weak self] _ in self?.decide(true) }),
    ])
    buttons.spacing = 8

    let words = UIStackView(arrangedSubviews: [line, buttons])
    words.axis = .vertical
    words.alignment = .leading
    words.spacing = 8
    let row = UIStackView(arrangedSubviews: [thumbnail, words])
    row.spacing = 12
    row.alignment = .center
    row.translatesAutoresizingMaskIntoConstraints = false
    contentView.addSubview(row)
    NSLayoutConstraint.activate([
      row.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 12),
      row.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -12),
      row.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 12),
      row.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -12),
    ])
  }

  required init?(coder: NSCoder) { nil }

  func place(in host: UIView) {
    translatesAutoresizingMaskIntoConstraints = false
    host.addSubview(self)
    NSLayoutConstraint.activate([
      leadingAnchor.constraint(equalTo: host.safeAreaLayoutGuide.leadingAnchor, constant: 12),
      trailingAnchor.constraint(equalTo: host.safeAreaLayoutGuide.trailingAnchor, constant: -12),
      // Clear of the composer and the keyboard, whichever is higher.
      bottomAnchor.constraint(equalTo: host.keyboardLayoutGuide.topAnchor, constant: -96),
    ])
    alpha = 0
    transform = CGAffineTransform(translationX: 0, y: 16)
    UIView.animate(withDuration: 0.25) {
      self.alpha = 1
      self.transform = .identity
    }
  }

  func decide(_ add: Bool) { onDecide(add) }
}

/// The few words the app draws itself, in the console's languages.
enum Words {
  private static let language = Locale.preferredLanguages.first.map { String($0.prefix(2)) } ?? "en"

  private static func pick(_ en: String, pl: String, de: String, es: String) -> String {
    switch language {
    case "pl": return pl
    case "de": return de
    case "es": return es
    default: return en
    }
  }

  static var offer: String {
    pick(
      "Add the photo you just took?", pl: "Dodać zdjęcie sprzed chwili?",
      de: "Das gerade aufgenommene Foto hinzufügen?", es: "¿Añadir la foto que acabas de hacer?")
  }
  static var add: String { pick("Add", pl: "Dodaj", de: "Hinzufügen", es: "Añadir") }
  static var notNow: String { pick("Not now", pl: "Nie teraz", de: "Nicht jetzt", es: "Ahora no") }
  static var photo: String { pick("Photo", pl: "Zdjęcie", de: "Foto", es: "Foto") }
}

@_cdecl("init_plugin_attach")
func initAttachPlugin() -> Plugin {
  AttachPlugin()
}
