import { svgAspect, visualFilename, type VisualKind } from "@/lib/visuals";

const MEDIA: Record<VisualKind, string> = {
  svg: "image/svg+xml",
  html: "text/html",
  mermaid: "text/plain",
};

/**
 * What a downloaded page may do, opened from disk: what the chat's frame lets it.
 *
 * In the chat a page runs under the policy the server sends; a file opened from
 * a download has none, so the same rules travel inside it - no request to
 * anywhere, scripts only inline or from this console's own library set. A page
 * that read something must not be able to send it on just by being opened.
 */
export function downloadPolicy(origin: string): string {
  return [
    "default-src 'none'",
    // i18n-exempt: a CSP directive, not copy
    `script-src 'unsafe-inline' 'unsafe-eval' data: blob: ${origin}`,
    // i18n-exempt: a CSP directive, not copy
    `style-src 'unsafe-inline' data: ${origin}`,
    "img-src data: blob:",
    // i18n-exempt: a CSP directive, not copy
    `font-src data: ${origin}`,
    "media-src data: blob:",
    "connect-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
    "frame-src 'none'",
  ].join("; ");
}

/** A page with `downloadPolicy` in its head - inserted after `<head>`, or first. */
export function sealedPage(html: string, origin: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${downloadPolicy(origin)}">`;
  const head = /<head\b[^>]*>/i.exec(html);
  if (head === null) return `${meta}${html}`;
  const at = head.index + head[0].length;
  return `${html.slice(0, at)}${meta}${html.slice(at)}`;
}

/** The drawing as a file: an SVG as itself, a page as HTML, a diagram as its source. */
export function downloadVisual(title: string, kind: VisualKind, content: string): void {
  const body = kind === "html" ? sealedPage(content, window.location.origin) : content;
  const url = URL.createObjectURL(new Blob([body], { type: `${MEDIA[kind]};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = visualFilename(title, kind);
  link.click();
  URL.revokeObjectURL(url);
}

/** The width an SVG is rasterised at, so a copied diagram is sharp when pasted. */
const RASTER_WIDTH = 2000;

/**
 * An SVG drawing as a PNG, `width` pixels wide and as tall as its `viewBox` says.
 *
 * Drawn through an `<img>`, which runs no script in an SVG, onto a canvas this
 * console owns - so nothing of the drawing executes here. Sized from the
 * `viewBox`, since a drawing that declares no width would otherwise come out at
 * the browser's default 300 pixels.
 *
 * Raises: whatever the browser refuses - an image it cannot decode, a canvas it
 * will not give.
 */
export async function svgPng(svg: string, width: number): Promise<Blob> {
  const aspect = svgAspect(svg) ?? 0.75;
  const height = Math.round(width * aspect);
  const sized = svg.replace(/<svg\b/i, `<svg width="${width}" height="${height}"`);
  const url = URL.createObjectURL(new Blob([sized], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    // i18n-exempt: never shown - the caller says it did not work in its own words
    if (context === null) throw new Error("The browser gave no canvas to draw on.");
    context.drawImage(image, 0, 0, width, height);
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    // i18n-exempt: never shown - the caller says it did not work in its own words
    if (png === null) throw new Error("The browser produced no image.");
    return png;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** An SVG drawing as a PNG on the clipboard, wide enough to paste sharp. */
export async function copySvgImage(svg: string): Promise<void> {
  const png = await svgPng(svg, RASTER_WIDTH);
  await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
}
