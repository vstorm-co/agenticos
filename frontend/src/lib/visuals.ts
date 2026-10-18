/**
 * Visuals: what a `draw` or `revise_visual` call shows, from its arguments.
 *
 * A visual lives in the call that drew it - the backend keeps no copy - so this
 * side rebuilds it the way `app/agents/capabilities/visuals/_toolset.py` does: a
 * drawing is its `content`, and a revision is the visual it names with its exact
 * replacements applied, in order. The two must agree, which is why the edit rule
 * here is `apply_edits`'s, word for word.
 */

import type { ToolCall } from "@/types";
import type { PartialField } from "./partial-args";

export const DRAW = "draw";
export const REVISE = "revise_visual";

/**
 * Whether a finished call drew something: its result opens on what the tool says
 * when it made a visual - the backend's `DREW`. A retry prompt or the last
 * attempt's refusal is a finished call too, and draws nothing.
 */
export function drewVisual(result: unknown): boolean {
  return typeof result === "string" && /^(Drew|Revised) /.test(result);
}

export type VisualKind = "svg" | "html" | "mermaid";

/** A call that leaves a visual behind, whose arguments are shown as they arrive. */
export function isVisualTool(name: string | undefined): boolean {
  return name === DRAW || name === REVISE;
}

/** The frame's starting height when the call names none, and the range it keeps to. */
export const DEFAULT_HEIGHT = 480;
const MIN_HEIGHT = 160;
const MAX_HEIGHT = 1200;

export function clampHeight(value: unknown, fallback = DEFAULT_HEIGHT): number {
  const number = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, number)));
}

export function visualKind(value: unknown): VisualKind | null {
  return value === "svg" || value === "html" || value === "mermaid" ? value : null;
}

const VIEW_BOX =
  /<svg\b[^>]*?\bviewBox\s*=\s*["']\s*[-+\d.eE]+[\s,]+[-+\d.eE]+[\s,]+([\d.eE+]+)[\s,]+([\d.eE+]+)/i;

/** Height over width of an SVG drawing, from its `viewBox`; null when it declares none. */
export function svgAspect(content: string): number | null {
  const match = VIEW_BOX.exec(content.slice(0, 4000));
  if (match === null) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  return width > 0 && height > 0 ? height / width : null;
}

/**
 * Whether this console is itself framed by another site - the widget on a
 * customer's page. A visual's frame allows only the console as its ancestor, so
 * nested there it would be refused; the panel shows a card instead.
 */
export function framedElsewhere(): boolean {
  return window.self !== window.top;
}

/** The renderer page on the content origin, beside the apps it shares a sandbox with. */
export function visualFrameUrl(artifactUrl: string): string {
  return `${visualContentBase(artifactUrl)}visual-frame`;
}

/**
 * Where the drawing frame lives, and so where a drawing's `lib/...` resolves.
 *
 * Ends in a slash: a drawing names its libraries relative to the frame, and a
 * downloaded copy has to name the same files absolutely.
 */
export function visualContentBase(artifactUrl: string): string {
  return `${artifactUrl.replace(/\/+$/, "")}/api/v1/artifact-content/`;
}

interface Edit {
  old: string;
  new: string;
}

function edits(value: unknown): Edit[] | null {
  if (!Array.isArray(value)) return null;
  const out: Edit[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) return null;
    const { old, new: next } = item as { old?: unknown; new?: unknown };
    if (typeof old !== "string" || old === "" || typeof next !== "string") return null;
    out.push({ old, new: next });
  }
  return out;
}

/** The text with each edit applied in order, or null when one does not name one place. */
export function applyEdits(source: string, changes: Edit[]): string | null {
  let text = source;
  for (const change of changes) {
    const at = text.indexOf(change.old);
    if (at < 0 || text.indexOf(change.old, at + 1) >= 0) return null;
    text = text.slice(0, at) + change.new + text.slice(at + change.old.length);
  }
  return text;
}

export interface ResolvedVisual {
  title: string;
  kind: VisualKind;
  content: string;
  height: number;
  /** Each picture the visual may use, by name, and the call that brought it. */
  images: Record<string, string>;
}

/** How many pictures one drawing may use - the backend's `MAX_IMAGES`. */
const MAX_IMAGES = 6;

/** Where a visual uses one of its pictures - the backend's `IMAGE_TOKEN`. */
const IMAGE_TOKEN = /\{\{image:([a-z0-9][a-z0-9_-]{0,39})\}\}/g;

/** The names a `draw` or `revise_visual` call gave its pictures. */
export function imageNames(args: Record<string, unknown>): string[] {
  const raw = args.images;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item: unknown) => {
    if (typeof item !== "object" || item === null) return [];
    const { name } = item as { name?: unknown };
    return typeof name === "string" ? [name] : [];
  });
}

/** The visual with each `{{image:NAME}}` it has a picture for replaced by its URI. */
export function inlineImages(content: string, uris: Readonly<Record<string, string>>): string {
  return content.replace(IMAGE_TOKEN, (token, name: string) => uris[name] ?? token);
}

const MAX_CHAIN = 50;

/**
 * The visual a finished call shows, revisions applied, or null when it cannot be
 * rebuilt from what is loaded - a revision of a visual in a page of the
 * conversation nobody has scrolled to, or one whose edits no longer apply.
 */
export function resolveVisual(
  call: Pick<ToolCall, "id" | "name" | "args">,
  known: ReadonlyMap<string, Pick<ToolCall, "id" | "name" | "args">>,
): ResolvedVisual | null {
  const chain: Pick<ToolCall, "id" | "name" | "args">[] = [];
  let current: Pick<ToolCall, "id" | "name" | "args"> | undefined = call;
  while (current !== undefined) {
    if (chain.length >= MAX_CHAIN) return null;
    chain.push(current);
    if (current.name !== REVISE) break;
    const base: unknown = current.args.visual_id;
    current = typeof base === "string" ? known.get(base) : undefined;
    if (current === undefined) return null;
  }
  const origin = (chain.at(-1) ?? call).args;
  const kind = visualKind(origin.kind);
  if (kind === null || typeof origin.content !== "string") return null;
  let content: string = origin.content;
  let title = typeof origin.title === "string" ? origin.title : "";
  const owner = chain.at(-1) ?? call;
  const images: Record<string, string> = Object.fromEntries(
    imageNames(origin).map((name) => [name, owner.id]),
  );
  for (const revision of chain.slice(0, -1).reverse()) {
    for (const name of imageNames(revision.args)) images[name] = revision.id;
    const changes = edits(revision.args.edits);
    const applied = changes === null ? null : applyEdits(content, changes);
    if (applied === null) return null;
    content = applied;
    if (typeof revision.args.title === "string" && revision.args.title.trim() !== "") {
      title = revision.args.title;
    }
  }
  // Only the pictures the drawing still uses, as the server keeps them: a long
  // chain of revisions may have added many, each one a download to show it.
  const used = new Set([...content.matchAll(IMAGE_TOKEN)].map((match) => match[1]));
  const kept = Object.fromEntries(
    Object.entries(images)
      .filter(([name]) => used.has(name))
      .slice(0, MAX_IMAGES),
  );
  return { title, kind, content, height: clampHeight(origin.height), images: kept };
}

/** What of a `draw` call has arrived while its arguments stream. */
export interface StreamedDrawing {
  title: string;
  kind: VisualKind | null;
  height: number | null;
  content: string;
}

export function streamedDrawing(fields: Record<string, PartialField>): StreamedDrawing {
  const title = fields.title?.value;
  const height = fields.height;
  const content = fields.content?.value;
  return {
    title: typeof title === "string" ? title : "",
    kind: fields.kind?.complete ? visualKind(fields.kind.value) : null,
    height: height?.complete && typeof height.value === "number" ? clampHeight(height.value) : null,
    content: typeof content === "string" ? content : "",
  };
}

/** A title as an app name: lower-case letters, digits and hyphens, as the server asks. */
export function appName(title: string): string {
  const slug = title
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "l")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/, "");
  return slug || "visual";
}

/** The name a downloaded visual is saved under. */
export function visualFilename(title: string, kind: VisualKind): string {
  const base = appName(title);
  const extension = kind === "svg" ? "svg" : kind === "mermaid" ? "mmd" : "html";
  return `${base}.${extension}`;
}
