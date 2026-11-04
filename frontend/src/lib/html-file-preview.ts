import type { FileText } from "./file-access";

import { WorkspacePreviewAssets } from "./css-file-preview";
import { HtmlPreviewAssetError } from "./preview-asset-path";
export { HtmlPreviewAssetError, relativeAssetPath } from "./preview-asset-path";

/**
 * Stylesheets are read through the same authorized source as the HTML. srcDoc
 * otherwise resolves style.css against the console URL, not the selected folder.
 * The iframe keeps its opaque origin and its no-scripts sandbox.
 */
export async function prepareHtmlFilePreview(
  path: string,
  file: FileText,
  readText: (path: string) => Promise<FileText>,
  readBytes?: (path: string) => Promise<Blob>,
): Promise<FileText> {
  const document = new DOMParser().parseFromString(file.content, "text/html");
  const assets = new WorkspacePreviewAssets(readText, readBytes);
  const links = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"]'));
  if (links.length > 16) throw new HtmlPreviewAssetError(path);
  for (const link of links) {
    const reference = link.getAttribute("href")?.trim() ?? "";
    if (reference === "") continue;
    try {
      const asset = assets.resolve(path, reference);
      if (asset === null) continue;
      const stylesheet = await assets.stylesheet(asset);
      assets.include(stylesheet);
      const style = document.createElement("style");
      style.textContent = stylesheet.replace(/<\/style/gi, "<\\/style");
      if (link.media) style.media = link.media;
      link.replaceWith(style);
    } catch (cause) {
      throw new HtmlPreviewAssetError(reference, { cause });
    }
  }
  return { ...file, content: `<!doctype html>\n${document.documentElement.outerHTML}` };
}
