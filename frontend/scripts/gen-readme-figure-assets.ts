/**
 * Write the pictures `docs/assets/readme/figures.html` draws with: lucide icons,
 * brand marks, agent faces and the AgenticOS mark, as one script of SVG strings.
 *
 * The figures page is plain HTML rendered once by hand - `docs/assets/readme/
 * render.mjs` turns each of its sections into the README's `.webp` files - so it
 * cannot import from the console. Everything it needs is copied here from the one
 * place the console draws it: lucide for icons, `brand-glyphs.generated.ts` for
 * marks, `blobatar` for faces and `logo.generated.ts` for the mark, so a figure
 * never shows a second drawing of anything the product shows.
 *
 *     bun run scripts/gen-readme-figure-assets.ts
 */
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { blobatar } from "blobatar";
import * as lucide from "lucide-react";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { BRAND_GLYPHS, PROVIDER_GLYPHS, type Glyph } from "../src/lib/brand-glyphs.generated";
import { LOGO_DATA_URI } from "../src/lib/logo.generated";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "..", "..", "docs", "assets", "readme", "figures-assets.js");

/** The lucide icons the figures name, by their component name. */
const ICONS = [
  "BookOpen",
  "Globe",
  "SquareTerminal",
  "ChartColumn",
  "Workflow",
  "ShieldCheck",
  "MessageSquare",
  "MessageCircle",
  "Code",
  "FileText",
  "LifeBuoy",
  "ChartLine",
  "CalendarClock",
  "Sparkles",
  "KeyRound",
  "Box",
  "LockKeyhole",
  "History",
  "EyeOff",
  "TriangleAlert",
  "Building2",
  "Users",
  "Network",
  "Database",
  "Cpu",
  "Cloud",
  "Plug",
  "Receipt",
  "Headset",
  "Lock",
  "Wallet",
  "UserCheck",
  "ScanEye",
  "Server",
  "HardDrive",
  "Link",
  "Zap",
  "Send",
  "Layers",
  "Mail",
  "Target",
  "RefreshCw",
  "Compass",
  "CircleHelp",
  "FileSearch",
  "Puzzle",
  "Webhook",
  "Brain",
  "Search",
  "Image",
  "AppWindow",
  "Clock",
  "Lightbulb",
  "Bot",
  "GitBranch",
  "Gauge",
  "Scaling",
  "ShieldAlert",
  "ArrowRight",
] as const;

/** The brand marks the figures name: `brand:x` from the brand set, `provider:x` from the providers. */
const MARKS = [
  "brand:slack",
  "brand:mattermost",
  "brand:telegram",
  "brand:gdrive",
  "brand:s3",
  "brand:github",
  "brand:microsoft",
  "brand:notion",
  "brand:linear",
  "brand:hubspot",
  "brand:stripe",
  "brand:figma",
  "brand:gitlab",
  "brand:sentry",
  "brand:postgres",
  "brand:asana",
  "brand:supabase",
  "brand:airtable",
  "brand:zapier",
  "brand:n8n",
  "brand:clickup",
  "brand:trello",
  "brand:miro",
  "brand:datadog",
  "brand:snowflake",
  "brand:bigquery",
  "brand:shopify",
  "brand:intercom",
  "brand:dropbox",
  "brand:gmail",
  "brand:atlassian",
  "brand:docker",
  "provider:openai",
  "provider:anthropic",
  "provider:google",
  "provider:mistral",
  "provider:deepseek",
  "provider:ollama",
  "provider:groq",
  "provider:openrouter",
  "provider:azure",
  "provider:bedrock",
  "provider:huggingface",
  "provider:xai",
  "provider:cohere",
] as const;

/** Agents and people in the figures, as faces: a seed and a hue from the console's set. */
const FACES: Record<string, { seed: string; hue: number }> = {
  invoice: { seed: "invoice-checker", hue: 140 },
  support: { seed: "support-triage", hue: 175 },
  strategy: { seed: "strategy", hue: 300 },
  report: { seed: "monday-report", hue: 55 },
  finance1: { seed: "kenji", hue: 205 },
  finance2: { seed: "priya", hue: 20 },
  finance3: { seed: "aneka", hue: 95 },
  ops1: { seed: "hanna", hue: 265 },
  ops2: { seed: "nora", hue: 330 },
  ops3: { seed: "amara", hue: 175 },
  board1: { seed: "mila", hue: 55 },
  board2: { seed: "leo", hue: 240 },
  agenticos: { seed: "agenticos", hue: 265 },
  pip: { seed: "pip", hue: 140 },
  momo: { seed: "momo", hue: 330 },
  atlas: { seed: "atlas", hue: 175 },
  tide: { seed: "tide", hue: 55 },
  dash: { seed: "dash", hue: 20 },
};

/** The same agents without their disc, for figures that draw them standing free. */
const BARE: Record<string, { seed: string; hue: number }> = {
  agenticos: { seed: "agenticos", hue: 265 },
  agent: { seed: "agent", hue: 20 },
  root: { seed: "root", hue: 240 },
  tofu: { seed: "tofu", hue: 205 },
  pebble: { seed: "pebble", hue: 300 },
  agentic: { seed: "agentic", hue: 140 },
  sprout: { seed: "sprout", hue: 95 },
  kiwi: { seed: "kiwi", hue: 175 },
  pip: { seed: "pip", hue: 140 },
  momo: { seed: "momo", hue: 330 },
  atlas: { seed: "atlas", hue: 175 },
  tide: { seed: "tide", hue: 55 },
  dash: { seed: "dash", hue: 20 },
};

function glyphSvg(glyph: Glyph): string {
  const paths = glyph.paths
    .map(
      (path) =>
        `<path d="${path.d}"${path.fillOpacity ? ` fill-opacity="${path.fillOpacity}"` : ""}/>`,
    )
    .join("");
  const fill = glyph.color ?? "currentColor";
  const rule = glyph.fillRule ? ` fill-rule="${glyph.fillRule}"` : "";
  return `<svg viewBox="${glyph.viewBox}" fill="${fill}"${rule}>${paths}</svg>`;
}

const icons = Object.fromEntries(
  ICONS.map((name) => {
    const icon = (lucide as unknown as Record<string, ComponentType<{ size: number }>>)[name];
    if (!icon) throw new Error(`lucide has no icon ${name}`);
    return [name, renderToStaticMarkup(createElement(icon, { size: 24 }))];
  }),
);

const marks = Object.fromEntries(
  MARKS.map((key) => {
    const [set, name] = key.split(":") as ["brand" | "provider", string];
    const table: Readonly<Record<string, Glyph>> = set === "brand" ? BRAND_GLYPHS : PROVIDER_GLYPHS;
    const glyph = table[name];
    if (!glyph) throw new Error(`no ${set} glyph ${name}`);
    return [name, glyphSvg(glyph)];
  }),
);

const faces = Object.fromEntries(
  Object.entries(FACES).map(([key, face]) => [
    key,
    blobatar(face.seed, { hue: face.hue, background: "circle" }),
  ]),
);

const bare = Object.fromEntries(
  Object.entries(BARE).map(([key, face]) => [
    key,
    blobatar(face.seed, { hue: face.hue, background: false }),
  ]),
);

writeFileSync(
  OUT,
  "// Generated by frontend/scripts/gen-readme-figure-assets.ts - do not edit.\n" +
    `window.FIGURE_ASSETS = ${JSON.stringify({ icons, marks, faces, bare, logo: LOGO_DATA_URI })};\n`,
);
console.log(`wrote ${OUT}`);
