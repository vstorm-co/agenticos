/** The source remains readable when a linked stylesheet cannot be prepared. */
export class HtmlPreviewAssetError extends Error {
  constructor(
    readonly path: string,
    options?: ErrorOptions,
  ) {
    super("HTML_PREVIEW_ASSET", options);
  }
}

/** Resolve a document-relative path without escaping the workspace root. */
export function relativeAssetPath(documentPath: string, reference: string): string | null {
  if (/^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(reference)) return null;
  const raw = decodeURIComponent(reference.split(/[?#]/, 1).join(""));
  if (raw.includes("\\") || raw.includes("\0")) throw new HtmlPreviewAssetError(reference);
  const parts = raw.startsWith("/") ? [] : documentPath.split("/").filter(Boolean).slice(0, -1);
  for (const part of raw.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (parts.length === 0) throw new HtmlPreviewAssetError(reference);
      parts.pop();
    } else parts.push(part);
  }
  return parts.join("/");
}
