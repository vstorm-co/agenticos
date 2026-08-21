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
 * import. Pick the source that already draws it; there is no fourth one, and a
 * hand-authored path is how a brand mark quietly stops being the brand's.
 */
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "..", "src", "lib", "brand-glyphs.generated.ts");

/**
 * Where a mark is drawn, by the people who own it.
 *
 * - `simple` — Simple Icons, the set behind `react-icons/si`. Every service and
 *   connector mark, monochrome and 24×24 by construction.
 * - `fontawesome` — the marks Simple Icons does not carry in the form the
 *   console used: AWS, Microsoft, and Slack's rounded hash. Their own
 *   viewBoxes.
 * - `lobehub` — the model-provider set, `Mono` variants. `icons/` in the static
 *   package *is* the monochrome form, which is what the console wants: a column
 *   where Gemini is four colours and OpenAI is ink reads as two products.
 */
type IconSet = "simple" | "fontawesome" | "lobehub";

// Simple Icons' own metadata, from the package the paths come from: it carries a
// brand `hex` per icon, which is the only honest source for a mark's colour. One
// fetch for the whole table rather than one per mark.
const SIMPLE_METADATA = "https://cdn.jsdelivr.net/npm/simple-icons@15/data/simple-icons.json";

const SOURCES: Readonly<Record<IconSet, (slug: string) => string>> = {
  simple: (slug) => `https://cdn.jsdelivr.net/npm/simple-icons@15/icons/${slug}.svg`,
  fontawesome: (slug) =>
    `https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6/svgs/brands/${slug}.svg`,
  lobehub: (slug) => `https://unpkg.com/@lobehub/icons-static-svg@1/icons/${slug}.svg`,
};

interface Source {
  readonly set: IconSet;
  readonly slug: string;
}

const simple = (slug: string): Source => ({ set: "simple", slug });
const fontawesome = (slug: string): Source => ({ set: "fontawesome", slug });
const lobehub = (slug: string): Source => ({ set: "lobehub", slug });

/**
 * Service and connector marks, keyed by the name the product uses.
 *
 * The key is the console's word, not the icon set's: `gdrive` rather than
 * `googledrive`, `postgres` rather than `postgresql`, `bigquery` rather than
 * `googlebigquery`. Renaming an upstream slug then changes one line here
 * instead of every call site.
 */
const BRANDS: Readonly<Record<string, Source>> = {
  airtable: simple("airtable"),
  asana: simple("asana"),
  atlassian: simple("atlassian"),
  aws: fontawesome("aws"),
  bigquery: simple("googlebigquery"),
  box: simple("box"),
  brave: simple("brave"),
  calendly: simple("calendly"),
  clickup: simple("clickup"),
  cloudflare: simple("cloudflare"),
  databricks: simple("databricks"),
  docker: simple("docker"),
  deepl: simple("deepl"),
  dropbox: simple("dropbox"),
  duckduckgo: simple("duckduckgo"),
  elastic: simple("elastic"),
  exa: lobehub("exa"),
  elevenlabs: simple("elevenlabs"),
  excalidraw: simple("excalidraw"),
  figma: simple("figma"),
  gdrive: simple("googledrive"),
  gitbook: simple("gitbook"),
  github: simple("github"),
  gitlab: simple("gitlab"),
  gmail: simple("gmail"),
  google: simple("google"),
  grafana: simple("grafana"),
  hubspot: simple("hubspot"),
  huggingface: simple("huggingface"),
  intercom: simple("intercom"),
  linear: simple("linear"),
  llamaparse: lobehub("llamaindex"),
  loom: simple("loom"),
  lucid: simple("lucid"),
  mailchimp: simple("mailchimp"),
  make: simple("make"),
  mattermost: simple("mattermost"),
  mcp: simple("modelcontextprotocol"),
  microsoft: fontawesome("microsoft"),
  miro: simple("miro"),
  mixpanel: simple("mixpanel"),
  n8n: simple("n8n"),
  netlify: simple("netlify"),
  notion: simple("notion"),
  pagerduty: simple("pagerduty"),
  paypal: simple("paypal"),
  postgres: simple("postgresql"),
  posthog: simple("posthog"),
  postman: simple("postman"),
  railway: simple("railway"),
  replit: simple("replit"),
  resend: simple("resend"),
  s3: fontawesome("aws"),
  semrush: simple("semrush"),
  sentry: simple("sentry"),
  shopify: simple("shopify"),
  similarweb: simple("similarweb"),
  slack: fontawesome("slack"),
  tavily: lobehub("tavily"),
  snowflake: simple("snowflake"),
  stripe: simple("stripe"),
  supabase: simple("supabase"),
  surveymonkey: simple("surveymonkey"),
  telegram: simple("telegram"),
  todoist: simple("todoist"),
  trello: simple("trello"),
  typeform: simple("typeform"),
  vercel: simple("vercel"),
  webflow: simple("webflow"),
  wix: simple("wix"),
  wordpress: simple("wordpress"),
  xero: simple("xero"),
  zapier: simple("zapier"),
  zoom: simple("zoom"),
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
  cerebras: lobehub("cerebras"),
  deepseek: lobehub("deepseek"),
  fireworks: lobehub("fireworks"),
  github: lobehub("github"),
  google: lobehub("gemini"),
  google_cloud: lobehub("vertexai"),
  groq: lobehub("groq"),
  mistral: lobehub("mistral"),
  moonshotai: lobehub("moonshot"),
  nebius: lobehub("nebius"),
  ollama: lobehub("ollama"),
  openai: lobehub("openai"),
  openrouter: lobehub("openrouter"),
  sambanova: lobehub("sambanova"),
  together: lobehub("together"),
  vercel: lobehub("vercel"),
  zai: lobehub("zai"),
};

interface GlyphPath {
  readonly d: string;
  readonly fillOpacity?: number;
}

interface Glyph {
  readonly viewBox: string;
  readonly fillRule?: "evenodd";
  readonly paths: readonly GlyphPath[];
  readonly color?: string;
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
 * still renders, still looks like a logo, and is the wrong logo.
 */
function parseGlyph(name: string, svg: string): Glyph {
  // The title is dropped because a mark is decorative here - `BrandIcon` adds
  // `role="img"` and a label where a caller wants it announced. The comment is
  // Font Awesome's licence banner, which is not dropped: it moves to the
  // generated file's header, where one copy covers all three sources.
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
    if (fill !== undefined && fill !== "currentColor" && fill !== "none") {
      throw new GlyphError(`${name}: a <path> is drawn in ${fill}, not currentColor`);
    }
    const opacity = attr("fill-opacity", tag[0]);
    paths.push(opacity === undefined ? { d } : { d, fillOpacity: Number(opacity) });
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

/**
 * Every Simple Icons brand colour, by slug, or an empty map if the fetch failed.
 *
 * Not fatal: a mark with no colour is drawn in `currentColor`, which is what
 * every mark did before colour existed here - so a metadata endpoint that moves
 * costs the marks their colour rather than costing the build its icons.
 */
async function fetchBrandColors(): Promise<Map<string, string>> {
  const res = await fetch(SIMPLE_METADATA, { redirect: "follow" });
  if (!res.ok) {
    console.warn(`brand colours: ${SIMPLE_METADATA} answered ${res.status} - marks stay ink`);
    return new Map();
  }
  // The package has shipped both shapes: a bare array, and an object wrapping one.
  const body: unknown = await res.json();
  const icons: readonly SimpleIconMeta[] = Array.isArray(body)
    ? (body as readonly SimpleIconMeta[])
    : ((body as { icons?: readonly SimpleIconMeta[] }).icons ?? []);
  return new Map(
    icons.map((icon) => [icon.slug ?? icon.title.toLowerCase(), `#${icon.hex}`] as const),
  );
}

interface SimpleIconMeta {
  readonly title: string;
  readonly slug?: string;
  readonly hex: string;
}

async function fetchGlyph(
  name: string,
  source: Source,
  colors: Map<string, string>,
): Promise<Glyph> {
  const url = SOURCES[source.set](source.slug);
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new GlyphError(`${name}: ${url} answered ${res.status}`);
  const glyph = parseGlyph(name, await res.text());
  if (source.set !== "simple") return glyph;
  // Every Simple Icons mark carries its colour, with no filter on which ones are
  // "worth" it. Colouring some and not others is what reads as a mistake: a grid
  // of marks is either one set in ink or one set in brand colours, and a surface
  // built to be scanned wants the second. Whether a colour is legible where it is
  // drawn is the caller's problem, not this file's - see `BrandIcon`.
  const color = colors.get(source.slug);
  return color === undefined ? glyph : { ...glyph, color };
}

/** Every mark in a table, fetched together, sorted by the product's own name. */
async function fetchAll(
  table: Readonly<Record<string, Source>>,
  colors: Map<string, string>,
): Promise<Map<string, Glyph>> {
  const entries = Object.entries(table).sort(([a], [b]) => a.localeCompare(b));
  return new Map(
    await Promise.all(
      entries.map(async ([name, source]): Promise<[string, Glyph]> => [
        name,
        await fetchGlyph(name, source, colors),
      ]),
    ),
  );
}

function renderPath(path: GlyphPath): string {
  const opacity = path.fillOpacity === undefined ? "" : `, fillOpacity: ${path.fillOpacity}`;
  return `{ d: ${JSON.stringify(path.d)}${opacity} }`;
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
//   Font Awesome Free   https://fontawesome.com/license   icons CC BY 4.0
//   @lobehub/icons      https://icons.lobehub.com         MIT

/** One filled shape of a mark. */
export interface GlyphPath {
  readonly d: string;
  /** Set where the mark layers one shape over another - Azure's three sheets. */
  readonly fillOpacity?: number;
}

/** A brand mark, drawn in \`currentColor\` at whatever size the caller asks for. */
export interface Glyph {
  readonly viewBox: string;
  /** Set where the mark's holes depend on it; \`nonzero\` is SVG's default. */
  readonly fillRule?: "evenodd";
  readonly paths: readonly GlyphPath[];
  /**
   * The brand's own colour, where drawing it in ink would lose the brand.
   *
   * Absent for a mark whose identity *is* monochrome: GitHub's \`#181717\` is the
   * text colour, so colouring it changes nothing on a light page and hides it on
   * a dark one. Decided at generation time by luminance, so no consumer knows
   * which brands are ink and no card carries a hardcoded hex. \`BrandIcon\` reads
   * it only when a caller asks, so every mark drawn today is unchanged.
   */
  readonly color?: string;
}

`;

const colors = await fetchBrandColors();
const brands = await fetchAll(BRANDS, colors);
const providers = await fetchAll(PROVIDERS, colors);

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
