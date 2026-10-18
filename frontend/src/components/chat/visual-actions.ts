import { saveBlob } from "@/lib/file-access";
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
 * anywhere, scripts only inline or from the drawing library set on `origin`, the
 * artifact origin the frame is served from. A page that read something must not
 * be able to send it on just by being opened.
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

/**
 * A page that runs from disk as it ran in the frame.
 *
 * The policy is the very first thing in the file, ahead of anything the drawing
 * wrote: the parser files a leading `<meta>` into the head it implies, so no
 * markup of the drawing's own can run or load before the policy applies. The
 * `lib/...` the drawing names relative to the frame become absolute under
 * `contentBase`, or the downloaded copy would open without its libraries.
 */
export function sealedPage(html: string, contentBase: string): string {
  const origin = new URL(contentBase).origin;
  const meta = `<meta http-equiv="Content-Security-Policy" content="${downloadPolicy(origin)}">`;
  return `${meta}${html.replace(/(["'(=]\s*)lib\//g, `$1${contentBase}lib/`)}`;
}

/** Elements that run something or embed another document, whatever they contain. */
const ACTIVE_SVG = new Set(["script", "iframe", "object", "embed", "audio", "video"]);

/** Attributes that name something to load or to jump to. */
const URL_ATTRIBUTES = new Set(["href", "xlink:href", "src"]);

/** A reference that stays inside the file: a fragment, or an inline picture. */
function inside(value: string): boolean {
  const trimmed = value.trim().toLowerCase();
  return trimmed.startsWith("#") || trimmed.startsWith("data:image/");
}

/** A stylesheet with every `url(...)` and `@import` that would reach outside the file emptied. */
function inertCss(css: string): string {
  return css
    .replace(/@import[^;]*;?/gi, "")
    .replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (whole, _quote: string, target: string) =>
      inside(target) ? whole : "none",
    );
}

/**
 * An SVG that does nothing when opened: no script, no handler, no request.
 *
 * A standalone SVG opened from disk carries no policy - nothing like the frame's
 * sandbox and CSP applies to it - so instead of sealing it, what could run or
 * reach out is taken out: scripts and embedded documents, `on*` handlers,
 * animations that rewrite a link, and any reference that is not a fragment or an
 * inline picture. What is left is the drawing.
 */
export function inertSvg(svg: string): string {
  const document = new DOMParser().parseFromString(svg, "image/svg+xml");
  if (document.getElementsByTagName("parsererror").length > 0) return "";
  for (const element of Array.from(document.querySelectorAll("*"))) {
    const name = element.localName.toLowerCase();
    if (ACTIVE_SVG.has(name)) {
      element.remove();
      continue;
    }
    if (
      (name === "animate" || name === "set") &&
      /href/i.test(element.getAttribute("attributeName") ?? "")
    ) {
      element.remove();
      continue;
    }
    if (name === "style") element.textContent = inertCss(element.textContent ?? "");
    for (const attribute of Array.from(element.attributes)) {
      const key = attribute.name.toLowerCase();
      if (key.startsWith("on")) element.removeAttribute(attribute.name);
      else if (URL_ATTRIBUTES.has(key) && !inside(attribute.value)) {
        element.removeAttribute(attribute.name);
      } else if (attribute.value.includes("url(")) {
        element.setAttribute(attribute.name, inertCss(attribute.value));
      }
    }
  }
  return new XMLSerializer().serializeToString(document);
}

/**
 * The drawing as a file: an SVG made inert, a page sealed, a diagram as its source.
 *
 * `contentBase` is where the frame is served (`visualContentBase`): the origin a
 * page's libraries come from, and the base its `lib/...` names resolve against.
 */
export function downloadVisual(
  title: string,
  kind: VisualKind,
  content: string,
  contentBase: string,
): void {
  const body =
    kind === "html"
      ? sealedPage(content, contentBase)
      : kind === "svg"
        ? inertSvg(content)
        : content;
  saveBlob(new Blob([body], { type: `${MEDIA[kind]};charset=utf-8` }), visualFilename(title, kind));
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
