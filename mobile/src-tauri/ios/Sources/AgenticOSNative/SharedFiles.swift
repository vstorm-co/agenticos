import Foundation
import UniformTypeIdentifiers

/// A file larger than this is named back rather than read into memory.
let maxSharedBytes = 20 * 1024 * 1024

/// Files handed to the console - shared from another app, picked, just
/// photographed - in the shape the app's `take_shared` and the console's
/// `parseShared` read: `{text, files: [{name, mimeType, data}], refused}`.
/// One file that cannot be read is named in `refused`; it must not lose the
/// rest.
struct SharedContent: Encodable {
  struct File: Encodable {
    let name: String
    let mimeType: String
    /// The bytes, base64.
    let data: String
  }

  var text = ""
  var files: [File] = []
  var refused: [String] = []

  mutating func add(_ url: URL, name: String? = nil) {
    let name = name ?? url.lastPathComponent
    let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
    guard size <= maxSharedBytes, let data = try? Data(contentsOf: url),
      data.count <= maxSharedBytes
    else {
      refused.append(name)
      return
    }
    add(data, name: name, type: UTType(filenameExtension: url.pathExtension))
  }

  mutating func add(_ data: Data, name: String, type: UTType?) {
    guard data.count <= maxSharedBytes else {
      refused.append(name)
      return
    }
    files.append(
      File(
        name: name,
        mimeType: type?.preferredMIMEType ?? "application/octet-stream",
        data: data.base64EncodedString()))
  }
}
