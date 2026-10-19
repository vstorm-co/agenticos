/**
 * Capture the product screens the annotated README figures are drawn over, and
 * where each annotated area is on them.
 *
 *     node docs/assets/readme/capture.mjs [http://localhost:3000]
 *
 * Signs in to a running deployment as the seeded owner, shoots the agent builder
 * and the dashboard in the light theme, and writes `shots/<name>.webp` plus
 * `shots/shots.js` - each picture's annotated areas as fractions of it, which is
 * what figures.html places its numbered outlines with. Run against demo data: whatever
 * the deployment holds is what the README shows.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const BASE = process.argv[2] ?? "http://localhost:3000";
/** How much of the builder's model card the figure shows, in CSS px. */
const MODEL_SHOWN = 290;
const VIEW = { width: 1440, height: 900 };
const out = join(here, "shots");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 2, colorScheme: "light" });
// The Architect's corner bubble would sit over the dashboard's last widget.
await context.addInitScript(() => {
  try {
    localStorage.setItem(
      "assistant-bubbles",
      JSON.stringify({ silenced: [], off: true, seenRun: null, docked: true }),
    );
  } catch {}
});
const page = await context.newPage();
await page.request.post(`${BASE}/api/auth/login`, {
  data: { email: "admin@example.com", password: "admin123" },
});

/** The picture's height; a figure that needs what is below the fold shoots taller. */
let height = VIEW.height;

/** A box as fractions of the picture, padded a little so the outline clears the content. */
function frac(box, pad = 8) {
  return {
    x: (box.x - pad) / VIEW.width,
    y: (box.y - pad) / height,
    w: (box.width + 2 * pad) / VIEW.width,
    h: (box.height + 2 * pad) / height,
  };
}

/** Nothing of the console's own chrome that is not the page: the Architect's corner button. */
async function tidy() {
  await page.addStyleTag({
    content: '[data-tour="assistant-launcher"], [aria-label="Open Architect"] { display: none !important; }',
  });
}

/** Every shot's areas and size, for figures.html - a file page cannot fetch the JSON. */
const shots = {};

async function shoot(name, areas) {
  shots[name] = { areas, width: VIEW.width, height };
  const png = join(out, `${name}.png`);
  await page.screenshot({ path: png });
  execFileSync("magick", [png, "-quality", "90", join(out, `${name}.webp`)]);
  execFileSync("rm", [png]);
  console.log(`wrote shots/${name}.webp`);
}

// The agent builder, on the template a new deployment installs.
const agents = await (await page.request.get(`${BASE}/api/agents?limit=100`)).json();
const agent = agents.items.find((item) => item.name === "Claude Code like") ?? agents.items[0];
await page.goto(`${BASE}/agents/${agent.id}`);
await page.waitForSelector('[data-tour="agent-instructions"]');
await page.waitForTimeout(1500);
await tidy();
// The page scrolls inside its own column, so a taller picture is a taller
// window: as tall as reaches the model card's provider and model fields, which
// is the part the figure names - the sampling settings under them are not.
const below = await page.locator('[data-tour="agent-model"]').boundingBox();
height = Math.round(below.y + MODEL_SHOWN);
await page.setViewportSize({ width: VIEW.width, height });
await page.waitForTimeout(800);
const title = await page.locator("h1").first().boundingBox();
const publish = await page.locator('[data-tour="agent-publish"]').boundingBox();
const tabs = await page.locator('[data-tour="agent-tab-build"]').locator("..").boundingBox();
const instructions = await page.locator('[data-tour="agent-instructions"]').boundingBox();
const model = await page.locator('[data-tour="agent-model"]').boundingBox();
await shoot("builder", [
  frac({ x: title.x, y: title.y, width: publish.x + publish.width - title.x, height: tabs.y - 12 - title.y }),
  frac(tabs),
  frac(instructions),
  frac({ ...model, height: MODEL_SHOWN - 30 }),
]);

// The dashboard, on the organization view, in a window of the usual size again.
height = VIEW.height;
await page.setViewportSize(VIEW);
await page.goto(`${BASE}/dashboard?view=organization`);
await page.waitForSelector('[data-tour="dashboard-filters"]');
await page.waitForTimeout(6000);
await tidy();
// The setup checklist is for a new deployment, not the picture of one in use.
const dismiss = page.getByText("Get started", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded')][1]").getByRole("button").last();
if (await dismiss.count()) await dismiss.click().catch(() => {});
height = 1150;
await page.setViewportSize({ width: VIEW.width, height });
await page.waitForTimeout(2500);
const filters = await page.locator('[data-tour="dashboard-filters"]').boundingBox();
const titled = async (text) => {
  const card = page
    .getByText(text, { exact: true })
    .first()
    .locator("xpath=ancestor::*[contains(@class,'rounded')][1]");
  const box = await card.boundingBox();
  return box && box.y < height ? frac({ ...box, height: Math.min(box.height, height - box.y - 12) }) : null;
};
await shoot(
  "dashboard",
  [
    frac(filters),
    await titled("This period at a glance"),
    await titled("Runs over time"),
    await titled("Outcomes"),
    await titled("Waiting on a decision"),
    await titled("Recent failures"),
  ].filter(Boolean),
);

writeFileSync(
  join(out, "shots.js"),
  `// Written by capture.mjs - do not edit.\nwindow.SHOTS = ${JSON.stringify(shots)};\n`,
);
await browser.close();
