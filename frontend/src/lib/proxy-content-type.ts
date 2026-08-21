/**
 * What the byte-proxy routes will render on this origin, and what they will not.
 *
 * These routes serve bytes from the API back to the browser *from the app's own
 * origin*, whose CSP allows `'unsafe-inline'` script. So the type a route passes
 * on cannot be the one the API guessed from a filename an uploader chose: a file
 * stored as `x.html` with `<script>` in it, accepted on a declared `Content-Type`
 * and never on its bytes, would be a script on this origin rather than the
 * picture the page asked for (#702, and #634 for the hosted-page logo). Each
 * route pins the type it emits against one of these sets; the backend pins it too,
 * both ends, because either alone is a single point of failure.
 */

/** The image types an avatar or logo route will emit; anything else is refused. */
export const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);

/**
 * The types safe to render inline on this origin - images and PDFs. A file route
 * that also serves spreadsheets and text serves anything outside this set as a
 * download (`Content-Disposition: attachment`), so `text/html` or an SVG is saved
 * rather than executed. A viewer that reads a file's bytes itself is unaffected;
 * this only governs what the browser renders directly.
 */
export const RENDER_SAFE_TYPES = new Set([...IMAGE_TYPES, "application/pdf"]);

/** The media type without its parameters - `image/png` from `image/png; charset=binary`. */
export function baseContentType(header: string | null): string {
  return (header ?? "").split(";")[0]?.trim() ?? "";
}
