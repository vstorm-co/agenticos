/**
 * Fetch every brand mark the console draws and write them to
 * `src/lib/brand-glyphs.generated.ts` as raw SVG path data.
 *
 * The console asks one question in three places - *what is the logo for this
 * third-party thing* - and it used to answer it with three mechanisms: a
 * `react-icons` import for a connector, a deep `@lobehub/icons` import for a
 * model provider, and `gen-mcp-logos.ts` for an MCP server's favicon. Two npm
 * packages worth 199 MB installed, to draw 87 marks. This is the same answer
 * `mcp-logos.generated.ts` already gave: pull what is needed at generation time
 * and check the result in, so the marks stay correct without the catalogues
 * behind them being a dependency. Run with: bun run gen:brand-icons
 *
 * **Adding a mark is editing a table here and re-running**, not adding an
 * import. Pick the source that already draws it - a full-colour set for a
 * service or connector, a mono set for a model provider - and never a
 * hand-authored path, which is how a brand mark quietly stops being the brand's.
 */
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "..", "src", "lib", "brand-glyphs.generated.ts");
const AUTH_OUT = join(here, "..", "src", "lib", "auth-glyphs.generated.ts");

/**
 * Where a mark is drawn, by the people who own it.
 *
 * - `simple` — Simple Icons, the set behind `react-icons/si`, monochrome and
 *   24×24 by construction. For a service whose full-colour mark has black and
 *   white parts (Notion, Intercom) or that no colour set draws.
 * - `logos` and `thesvg` — the full-colour sets, below; every other service and
 *   connector mark.
 * - `simple8` — the same set at 8.x, for a Microsoft product mark later releases
 *   dropped (Teams). Coloured by hand, from `MANUAL_COLORS`.
 * - `lobehub` — the model-provider set, `Mono` variants. `icons/` in the static
 *   package *is* the monochrome form, which is what the console wants: a column
 *   where Gemini is four colours and OpenAI is ink reads as two products.
 */
type IconSet = "simple" | "simple8" | "lobehub" | "logos" | "thesvg";

/**
 * The full-colour sets, for a service's or connector's mark (#2204).
 *
 * A grey glyph per service read as one icon repeated, and the mono sets drew some
 * of them wrong for want of a better shape - Slack as a single-colour hash,
 * SharePoint as the Windows logo, a Git repository as GitHub's cat. These draw
 * each brand in its own colours:
 *
 * - `logos` - SVG Logos by Gil Barbara, CC0, the `-icon` variants where one
 *   exists (the mark rather than the wordmark).
 * - `thesvg` - theSVG's colour set, MIT, for the marks SVG Logos lacks
 *   (SharePoint, MinIO, Gmail).
 *
 * Both are read from their Iconify JSON packages: one file per set rather than a
 * request per mark.
 */
const COLOR_SETS: Readonly<Partial<Record<IconSet, string>>> = {
  logos: "https://cdn.jsdelivr.net/npm/@iconify-json/logos@1.2.16/icons.json",
  thesvg: "https://cdn.jsdelivr.net/npm/@iconify-json/thesvg-color@1.2.18/icons.json",
};

const SOURCES: Readonly<Partial<Record<IconSet, (slug: string) => string>>> = {
  simple: (slug) => `https://cdn.jsdelivr.net/npm/simple-icons@15/icons/${slug}.svg`,
  // Simple Icons dropped its Microsoft product marks after 8.x; Teams is a
  // channel the console draws beside Slack, so it comes from the last release
  // that carried it.
  simple8: (slug) => `https://cdn.jsdelivr.net/npm/simple-icons@8/icons/${slug}.svg`,
  lobehub: (slug) => `https://unpkg.com/@lobehub/icons-static-svg@1/icons/${slug}.svg`,
};

interface Source {
  readonly set: IconSet;
  readonly slug: string;
  /** Drawn in the colours the file carries, one per path, rather than in one. */
  readonly coloured?: true;
}

const simple = (slug: string): Source => ({ set: "simple", slug });
const simple8 = (slug: string): Source => ({ set: "simple8", slug });
const lobehub = (slug: string): Source => ({ set: "lobehub", slug });
const logos = (slug: string): Source => ({ set: "logos", slug });
const thesvg = (slug: string): Source => ({ set: "thesvg", slug });
/** A lobehub `-color` file: the mark in the brand's own colours, path by path. */
const lobehubColour = (slug: string): Source => ({ set: "lobehub", slug, coloured: true });

/**
 * Service and connector marks, keyed by the name the product uses.
 *
 * The key is the console's word, not the icon set's: `gdrive` rather than
 * `googledrive`, `postgres` rather than `postgresql`, `bigquery` rather than
 * `googlebigquery`. Renaming an upstream slug then changes one line here
 * instead of every call site.
 */
const BRANDS: Readonly<Record<string, Source>> = {
  airtable: logos("airtable"),
  asana: logos("asana-icon"),
  atlassian: logos("atlassian"),
  aws: logos("aws"),
  bigquery: simple("googlebigquery"),
  box: logos("box"),
  brave: thesvg("brave"),
  buildkite: logos("buildkite-icon"),
  caldotcom: simple("caldotcom"),
  calendly: simple("calendly"),
  canva: simple("canva"),
  circleci: logos("circleci"),
  // The MCP clients Settings → MCP clients shows a setup for. VS Code has no
  // mark in any of the three sets (Simple Icons dropped it), so it takes a
  // lucide glyph at the call site instead.
  claude: logos("claude-icon"),
  claudecode: lobehub("claudecode"),
  // The coding agent capability's harness value, the same mark by another key.
  claude_code: lobehub("claudecode"),
  clerk: logos("clerk-icon"),
  clickup: logos("clickup-icon"),
  codex: lobehub("codex"),
  cloudflare: logos("cloudflare-icon"),
  contentful: logos("contentful"),
  cursor: lobehub("cursor"),
  databricks: logos("databricks-icon"),
  datadog: logos("datadog-icon"),
  deepl: thesvg("deepl"),
  docker: logos("docker-icon"),
  dropbox: logos("dropbox"),
  duckduckgo: thesvg("duckduckgo"),
  egnyte: simple("egnyte"),
  elastic: logos("elasticsearch"),
  elevenlabs: logos("elevenlabs-icon"),
  exa: logos("exa-icon"),
  excalidraw: thesvg("excalidraw"),
  figma: logos("figma"),
  // The connectors' own products, not their vendors' (#2204): a Git repository
  // on any host, SharePoint and OneDrive rather than the Windows logo.
  git: logos("git-icon"),
  onedrive: logos("microsoft-onedrive"),
  sharepoint: thesvg("microsoft-sharepoint"),
  gdrive: thesvg("google-drive"),
  gitbook: thesvg("gitbook"),
  github: logos("github-icon"),
  gitlab: logos("gitlab-icon"),
  gmail: thesvg("gmail"),
  google: logos("google-icon"),
  googleads: logos("google-ads"),
  googleanalytics: logos("google-analytics"),
  grafana: simple("grafana"),
  hubspot: thesvg("hubspot"),
  huggingface: simple("huggingface"),
  intercom: simple("intercom"),
  linear: thesvg("linear"),
  llamaparse: thesvg("llamaindex"),
  loom: logos("loom-icon"),
  lucid: thesvg("lucid"),
  mailchimp: thesvg("mailchimp"),
  make: thesvg("make"),
  mattermost: logos("mattermost-icon"),
  mcp: logos("model-context-protocol-icon"),
  meta: logos("meta-icon"),
  microsoft: logos("microsoft-icon"),
  microsoftteams: simple8("microsoftteams"),
  miro: simple("miro"),
  mixpanel: thesvg("mixpanel"),
  n8n: logos("n8n-icon"),
  netlify: logos("netlify-icon"),
  newrelic: logos("new-relic-icon"),
  notion: simple("notion"),
  pagerduty: logos("pagerduty-icon"),
  paypal: logos("paypal"),
  postgres: simple("postgresql"),
  posthog: logos("posthog-icon"),
  postman: logos("postman-icon"),
  pydantic: thesvg("pydantic"),
  railway: simple("railway"),
  render: thesvg("render"),
  replit: logos("replit-icon"),
  resend: logos("resend-icon"),
  s3: logos("aws-s3"),
  sanity: simple("sanity"),
  semrush: thesvg("semrush"),
  sentry: logos("sentry-icon"),
  shopify: logos("shopify"),
  similarweb: thesvg("similarweb"),
  slack: logos("slack-icon"),
  snowflake: logos("snowflake-icon"),
  storyblok: logos("storyblok-icon"),
  stripe: simple("stripe"),
  supabase: logos("supabase-icon"),
  surveymonkey: thesvg("surveymonkey"),
  tavily: thesvg("tavily"),
  telegram: logos("telegram"),
  todoist: logos("todoist-icon"),
  trello: logos("trello"),
  typeform: simple("typeform"),
  vercel: logos("vercel-icon"),
  webflow: thesvg("webflow"),
  wix: logos("wix"),
  wordpress: thesvg("wordpress"),
  xero: logos("xero"),
  zapier: logos("zapier-icon"),
  zoom: logos("zoom-icon"),
};

/**
 * Model-provider marks, keyed by the provider id `GET /providers/catalog`
 * serves.
 *
 * Kept apart from `BRANDS` because the two catalogs collide: `github` is a
 * connector *and* a model provider, `vercel` an MCP server *and* one - and the
 * mark differs. One table would have to pick a winner silently.
 */
const PROVIDERS: Readonly<Record<string, Source>> = {
  alibaba: lobehub("alibabacloud"),
  anthropic: lobehub("anthropic"),
  azure: lobehub("azure"),
  bedrock: lobehub("bedrock"),
  // BytePlus is ByteDance's cloud, and lobehub draws it with ByteDance's mark.
  byteplus: lobehub("bytedance"),
  cerebras: lobehub("cerebras"),
  cohere: lobehub("cohere"),
  deepseek: lobehub("deepseek"),
  // Text to speech's provider (#2259); a black mark, so it keeps the text colour.
  elevenlabs: lobehub("elevenlabs"),
  fireworks: lobehub("fireworks"),
  github: lobehub("github"),
  google: lobehub("gemini"),
  google_cloud: lobehub("vertexai"),
  groq: lobehub("groq"),
  heroku: simple("heroku"),
  huggingface: lobehub("huggingface"),
  mistral: lobehub("mistral"),
  moonshotai: lobehub("moonshot"),
  nebius: lobehub("nebius"),
  ollama: lobehub("ollama"),
  openai: lobehub("openai"),
  openai_codex: lobehub("codex"),
  openrouter: lobehub("openrouter"),
  ovhcloud: simple("ovh"),
  sambanova: lobehub("sambanova"),
  together: lobehub("together"),
  vercel: lobehub("vercel"),
  xai: lobehub("xai"),
  zai: lobehub("zai"),
};

interface GlyphPath {
  readonly d: string;
  readonly fillOpacity?: number;
  readonly fill?: string;
  readonly fillRule?: "evenodd";
}

interface Glyph {
  readonly viewBox: string;
  readonly fillRule?: "evenodd";
  readonly paths: readonly GlyphPath[];
  readonly color?: string;
}

/**
 * The brand colour of each mono mark whose set publishes none - lobehub ships
 * shapes only. Taken from each brand's own guidelines; a mark
 * missing here is drawn in the surrounding text colour, which is also what a
 * black or white brand gets (below).
 */
const MANUAL_COLORS: Readonly<Record<string, string>> = {
  claude: "#D97757",
  claudecode: "#D97757",
  claude_code: "#D97757",
  exa: "#1F40ED",
  microsoftteams: "#6264A7",
  alibaba: "#FF6A00",
  anthropic: "#D97757",
  azure: "#0078D4",
  bedrock: "#FF9900",
  cerebras: "#F15A29",
  cohere: "#39594D",
  deepseek: "#4D6BFE",
  fireworks: "#6720FF",
  google: "#3186FF",
  google_cloud: "#4285F4",
  groq: "#F55036",
  huggingface: "#FFB000",
  mistral: "#FA520F",
  openrouter: "#6467F2",
  sambanova: "#EE7624",
  together: "#0F6FFF",
};

/**
 * Whether a brand colour reads on both themes. A near-black mark vanishes on
 * the dark surface and a near-white one on the light, so GitHub, OpenAI,
 * Notion and the like keep the text colour, which is what their own
 * guidelines ask of a mark on an arbitrary background anyway.
 */
function readsOnBothThemes(hex: string): boolean {
  const channel = (offset: number) => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  return luminance > 0.035 && luminance < 0.8;
}

/** Simple Icons' published colour for each slug, read once from its data file. */
async function simpleColors(): Promise<Map<string, string>> {
  const url = "https://cdn.jsdelivr.net/npm/simple-icons@15/data/simple-icons.json";
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new GlyphError(`${url} answered ${res.status}`);
  const icons = (await res.json()) as { slug: string; hex: string }[];
  return new Map(icons.map((icon) => [icon.slug, `#${icon.hex.toUpperCase()}`]));
}

/** The colour a mark is drawn in, or none for the text colour. */
function colorFor(name: string, source: Source): string | undefined {
  const hex = source.set === "simple" ? SIMPLE_COLORS.get(source.slug) : MANUAL_COLORS[name];
  return hex !== undefined && readsOnBothThemes(hex) ? hex : undefined;
}

const SVG_OPEN = /<svg\b[^>]*>/;
const PATH_TAG = /<path\b[^>]*?\/?>/g;

class GlyphError extends Error {}

/** The value of `attribute` on an already-isolated tag, or `undefined`. */
function attr(attribute: string, tag: string): string | undefined {
  const match = new RegExp(`\\b${attribute}="([^"]*)"`).exec(tag);
  return match === null ? undefined : match[1];
}

/**
 * `pattern` removed from `text`, repeatedly, until removing it changes nothing.
 *
 * One pass is not enough for a pattern whose own opener can survive it:
 * `<!--<!-- -->` loses the inner comment and leaves a bare `<!--` behind, which
 * the leftover check would then read as unsupported markup for a file that has
 * none. Removing to a fixed point is also what makes this not the incomplete
 * multi-character sanitization CodeQL flags - the input here is fetched, not
 * typed, but "the source is trusted" is the assumption every one of those
 * findings was written under.
 */
function stripAll(text: string, pattern: RegExp): string {
  let current = text;
  for (
    let next = current.replace(pattern, "");
    next !== current;
    next = current.replace(pattern, "")
  ) {
    current = next;
  }
  return current;
}

/**
 * The drawable part of one source SVG.
 *
 * Deliberately narrow: a `viewBox`, an optional `fill-rule`, and paths. Anything
 * else in the file - a `<g>`, a `<circle>`, a gradient, a literal `fill` colour -
 * throws rather than being dropped, because a mark that silently loses a layer
 * still renders, still looks like a logo, and is the wrong logo. A `coloured`
 * source is the one exception to the last: its paths keep their hex colours.
 */
function parseGlyph(name: string, svg: string, coloured = false): Glyph {
  // The title is dropped because a mark is decorative here - `BrandIcon` adds
  // `role="img"` and a label where a caller wants it announced. A comment is a
  // set's licence banner, which the generated file's header carries for every
  // source at once.
  const withoutTitle = stripAll(stripAll(svg, /<title>[\s\S]*?<\/title>/g), /<!--[\s\S]*?-->/g);
  const open = SVG_OPEN.exec(withoutTitle);
  if (open === null) throw new GlyphError(`${name}: no <svg> element`);

  const viewBox = attr("viewBox", open[0]);
  if (viewBox === undefined) throw new GlyphError(`${name}: <svg> has no viewBox`);

  const rule = attr("fill-rule", open[0]);
  if (rule !== undefined && rule !== "evenodd" && rule !== "nonzero") {
    throw new GlyphError(`${name}: unsupported fill-rule ${rule}`);
  }

  const paths: GlyphPath[] = [];
  for (const tag of withoutTitle.matchAll(PATH_TAG)) {
    const d = attr("d", tag[0]);
    if (d === undefined) throw new GlyphError(`${name}: a <path> has no d`);
    const fill = attr("fill", tag[0]);
    const hex =
      fill !== undefined && /^#[0-9A-Fa-f]{6}$/.test(fill) ? fill.toUpperCase() : undefined;
    if (coloured && hex === undefined) {
      throw new GlyphError(`${name}: a <path> of a coloured mark has no hex fill`);
    }
    if (!coloured && fill !== undefined && fill !== "currentColor" && fill !== "none") {
      throw new GlyphError(`${name}: a <path> is drawn in ${fill}, not currentColor`);
    }
    const opacity = attr("fill-opacity", tag[0]);
    paths.push({
      d,
      ...(opacity === undefined ? {} : { fillOpacity: Number(opacity) }),
      ...(hex === undefined ? {} : { fill: hex }),
    });
  }
  if (paths.length === 0) throw new GlyphError(`${name}: no <path> to draw`);

  const leftover = withoutTitle
    .replace(SVG_OPEN, "")
    .replace(PATH_TAG, "")
    .replace(/<\/path>|<\/svg>/g, "")
    .trim();
  if (leftover !== "") throw new GlyphError(`${name}: unsupported markup ${leftover.slice(0, 80)}`);

  return rule === "evenodd" ? { viewBox, fillRule: "evenodd", paths } : { viewBox, paths };
}

async function fetchGlyph(name: string, source: Source): Promise<Glyph> {
  const collection = COLOR_SETS[source.set];
  if (collection !== undefined) {
    return parseColorGlyph(name, await colorSvg(collection, name, source.slug));
  }
  const url = SOURCES[source.set]!(source.slug);
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new GlyphError(`${name}: ${url} answered ${res.status}`);
  const glyph = parseGlyph(name, await res.text(), source.coloured);
  if (source.coloured) return glyph;
  const color = colorFor(name, source);
  return color === undefined ? glyph : { ...glyph, color };
}

interface IconifyIcon {
  readonly body: string;
  readonly width?: number;
  readonly height?: number;
  readonly left?: number;
  readonly top?: number;
}

interface IconifySet {
  readonly icons: Readonly<Record<string, IconifyIcon>>;
  readonly width?: number;
  readonly height?: number;
}

const iconifySets = new Map<string, Promise<IconifySet>>();

/** One mark of an Iconify set as a standalone SVG, the set fetched once. */
async function colorSvg(url: string, name: string, slug: string): Promise<string> {
  let set = iconifySets.get(url);
  if (set === undefined) {
    set = fetch(url, { redirect: "follow" }).then(async (res) => {
      if (!res.ok) throw new GlyphError(`${url} answered ${res.status}`);
      return (await res.json()) as IconifySet;
    });
    iconifySets.set(url, set);
  }
  const loaded = await set;
  const icon = loaded.icons[slug];
  if (icon === undefined) throw new GlyphError(`${name}: ${slug} is not in ${url}`);
  const width = icon.width ?? loaded.width ?? 16;
  const height = icon.height ?? loaded.height ?? 16;
  const viewBox = `${icon.left ?? 0} ${icon.top ?? 0} ${width} ${height}`;
  return `<svg viewBox="${viewBox}">${icon.body}</svg>`;
}

/** Below this luminance a fill vanishes on the dark theme; it takes the text colour. */
const NEAR_BLACK = 0.035;

function luminance(hex: string): number {
  const channel = (offset: number) => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

const NAMED: Readonly<Record<string, string>> = { white: "#FFFFFF", black: "#000000" };

/** A fill as `#RRGGBB`, `none`, or `undefined` for one this does not draw. */
function hexOf(fill: string): string | undefined {
  const value = NAMED[fill.toLowerCase()] ?? fill;
  if (/^#[0-9a-f]{3}$/i.test(value)) {
    return `#${[...value.slice(1)].map((c) => c + c).join("")}`.toUpperCase();
  }
  return /^#[0-9a-f]{6}$/i.test(value) ? value.toUpperCase() : undefined;
}

const SHAPE = /<(\/?)(g|path|circle|ellipse|rect|polygon)\b([^>]*?)(\/?)>/g;

/** A basic shape as path data, so the renderer draws paths and nothing else. */
function shapeToPath(name: string, tag: string, attrs: string): string {
  const num = (attribute: string, fallback = 0) => {
    const value = attr(attribute, attrs);
    return value === undefined ? fallback : Number(value);
  };
  if (tag === "path") {
    const d = attr("d", attrs);
    if (d === undefined) throw new GlyphError(`${name}: a <path> has no d`);
    return d;
  }
  if (tag === "circle" || tag === "ellipse") {
    const [cx, cy] = [num("cx"), num("cy")];
    const rx = tag === "circle" ? num("r") : num("rx");
    const ry = tag === "circle" ? num("r") : num("ry");
    return `M${cx - rx} ${cy}a${rx} ${ry} 0 1 0 ${2 * rx} 0a${rx} ${ry} 0 1 0 ${-2 * rx} 0Z`;
  }
  if (tag === "rect") {
    const [x, y, w, h] = [num("x"), num("y"), num("width"), num("height")];
    const r = Math.min(num("rx", num("ry")), w / 2, h / 2);
    if (r === 0) return `M${x} ${y}h${w}v${h}h${-w}Z`;
    return (
      `M${x + r} ${y}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}v${h - 2 * r}` +
      `a${r} ${r} 0 0 1 ${-r} ${r}h${-(w - 2 * r)}a${r} ${r} 0 0 1 ${-r} ${-r}` +
      `v${-(h - 2 * r)}a${r} ${r} 0 0 1 ${r} ${-r}Z`
    );
  }
  const points = attr("points", attrs);
  if (points === undefined) throw new GlyphError(`${name}: a <polygon> has no points`);
  return `M${points.trim()}Z`;
}

/**
 * The drawable part of one full-colour mark: paths, each in its own colour.
 *
 * Wider than `parseGlyph`, and still narrow where it matters. Groups pass their
 * `fill` and `fill-rule` down; circles, ellipses, rectangles and polygons become
 * path data. A gradient is drawn as its middle stop: at the sixteen to forty
 * pixels these marks are drawn at it reads the same, and a flat colour needs no
 * `<defs>` - whose ids collide when one mark is on a page twice. A near-black fill
 * takes the text colour, or the mark would vanish on the dark theme. Anything
 * else - a transform, a mask, a clip path, a `<use>`, a filter, a style attribute
 * - throws: a mark that silently loses a layer is the wrong logo, and another
 * source is chosen for it instead.
 */
function parseColorGlyph(name: string, svg: string): Glyph {
  const open = SVG_OPEN.exec(svg);
  const viewBox = open === null ? undefined : attr("viewBox", open[0]);
  if (viewBox === undefined) throw new GlyphError(`${name}: <svg> has no viewBox`);

  // A gradient's middle stop, or `null` for a shading one - a stop fading to
  // nothing, laid over a shape to give it depth - whose shapes are left out.
  const gradients = new Map<string, string | null>();
  const gradientPattern = /<(linearGradient|radialGradient)\b([^>]*)>([\s\S]*?)<\/\1>/g;
  for (const [, , head, inner] of svg.matchAll(gradientPattern)) {
    const id = attr("id", head!);
    const stopTags = [...inner!.matchAll(/<stop\b[^>]*>/g)].map((stop) => stop[0]);
    const shading = stopTags.some((stop) => attr("stop-opacity", stop) === "0");
    const stops = stopTags.map((stop) => hexOf(attr("stop-color", stop) ?? "#000000"));
    const middle = stops[Math.floor((stops.length - 1) / 2)];
    if (id === undefined || (!shading && middle === undefined)) {
      throw new GlyphError(`${name}: a gradient this cannot flatten`);
    }
    gradients.set(id, shading ? null : middle!);
  }
  const body = svg.replace(/<defs>[\s\S]*?<\/defs>/g, "");
  if (
    /<(use|mask|clipPath|filter|image|text|pattern)\b|\btransform=|\bstyle=|\bclip-path=/.test(body)
  ) {
    throw new GlyphError(`${name}: markup a flat path cannot carry`);
  }

  const inherited: { fill?: string; rule?: string }[] = [{}];
  const paths: GlyphPath[] = [];
  for (const [, closing, tag, attrs, selfClosing] of body.matchAll(SHAPE)) {
    const top = inherited[inherited.length - 1]!;
    if (tag === "g") {
      if (closing) inherited.pop();
      else if (!selfClosing) {
        inherited.push({
          fill: attr("fill", attrs!) ?? top.fill,
          rule: attr("fill-rule", attrs!) ?? top.rule,
        });
      }
      continue;
    }
    if (closing) continue;
    const raw = attr("fill", attrs!) ?? top.fill;
    if (raw === "none") continue;
    const gradient = raw?.match(/^url\(#(.+)\)$/)?.[1];
    if (gradient !== undefined && gradients.get(gradient) === null) continue;
    const hex =
      gradient !== undefined
        ? (gradients.get(gradient) ?? undefined)
        : raw === undefined
          ? "#000000"
          : hexOf(raw);
    if (hex === undefined) throw new GlyphError(`${name}: a fill this cannot draw: ${raw}`);
    const opacity = attr("fill-opacity", attrs!);
    const rule = attr("fill-rule", attrs!) ?? top.rule;
    paths.push({
      d: shapeToPath(name, tag!, attrs!),
      ...(luminance(hex) < NEAR_BLACK ? {} : { fill: hex }),
      ...(rule === "evenodd" ? { fillRule: "evenodd" as const } : {}),
      ...(opacity === undefined ? {} : { fillOpacity: Number(opacity) }),
    });
  }
  if (paths.length === 0) throw new GlyphError(`${name}: no shape to draw`);
  // Ink that becomes the text colour beside white that stays white is a mark
  // that turns into one light blob on the dark theme - Notion's box, a
  // PostgreSQL elephant. Such a mark is drawn from a mono set instead.
  const inked = paths.some((path) => path.fill === undefined);
  const white = paths.some((path) => path.fill !== undefined && luminance(path.fill) > 0.8);
  if (inked && white) throw new GlyphError(`${name}: black and white parts, unreadable on dark`);
  return { viewBox, paths };
}

/** Every mark in a table, fetched together, sorted by the product's own name. */
async function fetchAll(table: Readonly<Record<string, Source>>): Promise<Map<string, Glyph>> {
  const entries = Object.entries(table).sort(([a], [b]) => a.localeCompare(b));
  const settled = await Promise.allSettled(
    entries.map(async ([name, source]): Promise<[string, Glyph]> => [
      name,
      await fetchGlyph(name, source),
    ]),
  );
  // Every refusal at once: a table of ninety marks fixed one failure per run is
  // ninety runs.
  const failed = settled.flatMap((result) =>
    result.status === "rejected" ? [String(result.reason)] : [],
  );
  if (failed.length > 0) throw new GlyphError(failed.join("\n"));
  return new Map(
    settled.flatMap((result) => (result.status === "fulfilled" ? [result.value] : [])),
  );
}

function renderPath(path: GlyphPath): string {
  const opacity = path.fillOpacity === undefined ? "" : `, fillOpacity: ${path.fillOpacity}`;
  const fill = path.fill === undefined ? "" : `, fill: ${JSON.stringify(path.fill)}`;
  const rule = path.fillRule === undefined ? "" : `, fillRule: "evenodd"`;
  return `{ d: ${JSON.stringify(path.d)}${opacity}${fill}${rule} }`;
}

function renderGlyph(glyph: Glyph): string {
  const rule = glyph.fillRule === undefined ? "" : `\n    fillRule: "evenodd",`;
  const color = glyph.color === undefined ? "" : `\n    color: ${JSON.stringify(glyph.color)},`;
  const paths = glyph.paths.map((path) => `      ${renderPath(path)},`).join("\n");
  return `{\n    viewBox: ${JSON.stringify(glyph.viewBox)},${rule}${color}\n    paths: [\n${paths}\n    ],\n  }`;
}

function renderTable(name: string, type: string, glyphs: Map<string, Glyph>): string {
  const rows = [...glyphs]
    .map(([key, glyph]) => `  ${JSON.stringify(key)}: ${renderGlyph(glyph)},`)
    .join("\n");
  return `export const ${name}: Readonly<Record<${type}, Glyph>> = {\n${rows}\n};\n`;
}

const HEADER = `// AUTO-GENERATED by scripts/gen-brand-icons.ts - do not edit by hand.
// Brand marks for the services, connectors and model providers the console
// draws, as raw SVG path data. One mechanism rather than three npm icon
// catalogues; regenerate with: bun run gen:brand-icons
//
// The marks are the trademark holders'. The path data is redistributed from:
//   Simple Icons        https://simpleicons.org           CC0 1.0
//   @lobehub/icons      https://icons.lobehub.com         MIT
//   SVG Logos           https://github.com/gilbarbara/logos  CC0 1.0
//   theSVG              https://github.com/glincker/thesvg   MIT

/** One filled shape of a mark. */
export interface GlyphPath {
  readonly d: string;
  /** Set where the mark layers one shape over another - Azure's three sheets. */
  readonly fillOpacity?: number;
  /**
   * This shape's own colour, in a full-colour mark. Absent, the shape takes the
   * mark's colour - the brand's, or the text colour.
   */
  readonly fill?: string;
  readonly fillRule?: "evenodd";
}

/** A brand mark, drawn at whatever size the caller asks for. */
export interface Glyph {
  readonly viewBox: string;
  /** Set where the mark's holes depend on it; \`nonzero\` is SVG's default. */
  readonly fillRule?: "evenodd";
  readonly paths: readonly GlyphPath[];
  /**
   * The brand's own colour, where it reads on both themes. Absent for a black
   * or white brand and for one whose set publishes no colour, which then takes
   * the surrounding text colour.
   */
  readonly color?: string;
}

`;

const SIMPLE_COLORS = await simpleColors();
const brands = await fetchAll(BRANDS);
const providers = await fetchAll(PROVIDERS);

const union = [...brands.keys()].map((name) => `  | ${JSON.stringify(name)}`).join("\n");
const body =
  HEADER +
  `/** Every service or connector this build draws a mark for. */\nexport type BrandName =\n${union};\n\n` +
  renderTable("BRAND_GLYPHS", "BrandName", brands) +
  "\n/** Model-provider marks, keyed by the id `GET /providers/catalog` serves. */\n" +
  renderTable("PROVIDER_GLYPHS", "string", providers);

await writeFile(OUT, body, "utf8");
// Formatted here rather than left to the pre-commit hook, so that regenerating
// and running `make lint` in the same breath does not fail on the file this
// script just wrote.
execFileSync("bunx", ["prettier", "--write", "--log-level", "warn", OUT], { stdio: "inherit" });
console.log(
  `Wrote ${brands.size} brand and ${providers.size} provider marks ` +
    `(${Math.round(body.length / 1024)} KB) → ${OUT}`,
);

// `BrandIcon` reads the 89-mark table by dynamic key, which no bundler can
// tree-shake, so the auth pages get their own tiny module of the marks they
// draw rather than shipping every mark on the sign-in critical path (#955).
//
// A sign-in button is where a provider's guidelines ask for the full-colour
// mark - Google's four-colour G, Microsoft's four squares - so those two are
// fetched in colour here, while the catalogue keeps one colour per mark. GitHub
// has no colour form; it stays the mark the catalogue draws.
const AUTH_SOURCES: Readonly<Record<"github" | "google" | "microsoft", Source | null>> = {
  github: null,
  google: lobehubColour("google-color"),
  microsoft: lobehubColour("microsoft-color"),
};
const authKeys = Object.keys(AUTH_SOURCES) as (keyof typeof AUTH_SOURCES)[];
const authGlyphs = new Map(
  await Promise.all(
    authKeys.map(async (key) => {
      const source = AUTH_SOURCES[key];
      const glyph = source === null ? brands.get(key) : await fetchGlyph(key, source);
      if (!glyph) throw new Error(`auth glyph missing from BRANDS: ${key}`);
      return [key, glyph] as const;
    }),
  ),
);
const authUnion = authKeys.map((name) => `  | ${JSON.stringify(name)}`).join("\n");
const authBody =
  "// AUTO-GENERATED by scripts/gen-brand-icons.ts - do not edit by hand.\n" +
  "// The identity-provider marks the sign-in and register pages draw, kept out\n" +
  "// of the full brand table so those pages ship only the marks they use.\n" +
  '// Regenerate with: bun run gen:brand-icons\n\nimport type { Glyph } from "./brand-glyphs.generated";\n\n' +
  `/** The identity providers the auth pages can offer. */\nexport type AuthProvider =\n${authUnion};\n\n` +
  renderTable("AUTH_GLYPHS", "AuthProvider", authGlyphs);

await writeFile(AUTH_OUT, authBody, "utf8");
execFileSync("bunx", ["prettier", "--write", "--log-level", "warn", AUTH_OUT], {
  stdio: "inherit",
});
console.log(`Wrote ${authGlyphs.size} auth marks → ${AUTH_OUT}`);
