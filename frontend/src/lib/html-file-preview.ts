import type { FileText } from "./file-access";

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

/**
 * Stylesheets are read through the same authorized source as the HTML. srcDoc
 * otherwise resolves style.css against the console URL, not the selected folder.
 * The iframe keeps its opaque origin and its no-scripts sandbox.
 */
export async function prepareHtmlFilePreview(
  path: string,
  file: FileText,
  readText: (path: string) => Promise<FileText>,
): Promise<FileText> {
  const document = new DOMParser().parseFromString(file.content, "text/html");
  const links = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"]'));
  if (links.length > 16) throw new HtmlPreviewAssetError(path);
  for (const link of links) {
    const reference = link.getAttribute("href")?.trim() ?? "";
    if (reference === "") continue;
    try {
      const asset = relativeAssetPath(path, reference);
      if (asset === null) continue;
      const stylesheet = await readText(asset);
      if (stylesheet.truncated) throw new HtmlPreviewAssetError(asset);
      const style = document.createElement("style");
      style.textContent = stylesheet.content.replace(/<\/style/gi, "<\\/style");
      if (link.media) style.media = link.media;
      link.replaceWith(style);
    } catch (cause) {
      throw new HtmlPreviewAssetError(reference, { cause });
    }
  }
  return { ...file, content: `<!doctype html>\n${document.documentElement.outerHTML}` };
}
