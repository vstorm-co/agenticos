/**
 * Capture the console screens the decks show, and where each annotated area is.
 *
 *     ORG="Northwind Labs" node docs/presentation/capture.mjs            # every screen
 *     ORG="Northwind Labs" node docs/presentation/capture.mjs chat agents # just these
 *     PREVIEW=1 node docs/presentation/capture.mjs builder               # also draw the areas
 *
 * Signs in to a running deployment as the seeded owner and, in the organization
 * `ORG` names, shoots each screen below in the light theme at 1440 pixels wide and
 * device scale 2. It writes `media/<name>.webp` and `media/areas.js`: every
 * screen's named areas as fractions of its picture. The decks refer to an area by
 * name - `data-focus="@builder.instructions"` - so a recapture moves the camera
 * and the numbered outlines with the screen instead of leaving them where the
 * old one had its controls. `PREVIEW=1` also writes each picture with its areas
 * drawn on, into a temporary folder it names, to check them before a deck is opened.
 *
 * The figures shared with the README come from its own render; run
 * `../assets/readme/render.mjs` first when one of them changed.
 *
 * What a screen shows is whatever the organization holds: run it against the demo
 * data you want presented. Playwright and ImageMagick come from the developer's
 * machine, like the README figures.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const EMAIL = process.env.OWNER_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.OWNER_PASSWORD ?? "admin123";
const ORG = process.env.ORG;
const PREVIEW = Boolean(process.env.PREVIEW);
const WIDTH = 1440;
const only = new Set(process.argv.slice(2));
const media = join(here, "media");

/** The box of whatever `locator` finds first, in CSS pixels. */
async function box(locator) {
  const found = await locator.first().boundingBox();
  if (!found) throw new Error(`nothing to measure: ${locator}`);
  return found;
}

/** The nearest ancestor of the text `text` that is drawn as a card or a panel. */
function card(page, text, scope = "main") {
  return page
    .locator(scope)
    .getByText(text, { exact: true })
    .first()
    .locator("xpath=ancestor::*[contains(@class,'rounded') and (contains(@class,'border') or contains(@class,'shadow') or contains(@class,'bg-'))][1]");
}

/**
 * The first ancestor of the text `text` that `fits` accepts - a panel taller than
 * a line, a row wider than a column. For layouts with no card class to anchor on.
 */
async function climb(page, text, fits, { last = false } = {}) {
  const found = page.getByText(text, { exact: true });
  const handle = await (last ? found.last() : found.first()).elementHandle();
  if (!handle) throw new Error(`no text to climb from: ${text}`);
  return handle.evaluate((element, source) => {
    // eslint-disable-next-line no-new-func
    const accept = new Function("r", "e", `return (${source})(r, e)`);
    for (let node = element; node; node = node.parentElement) {
      const r = node.getBoundingClientRect();
      if (accept(r, node)) return { x: r.x, y: r.y, width: r.width, height: r.height };
    }
    throw new Error("no ancestor fits");
  }, fits.toString());
}

/** One box around several. */
function union(...boxes) {
  const x = Math.min(...boxes.map((b) => b.x));
  const y = Math.min(...boxes.map((b) => b.y));
  const right = Math.max(...boxes.map((b) => b.x + b.width));
  const bottom = Math.max(...boxes.map((b) => b.y + b.height));
  return { x, y, width: right - x, height: bottom - y };
}

/** A box cut to `height` from its top - the part of a long card a slide talks about. */
const top = (b, height) => ({ ...b, height: Math.min(b.height, height) });

/**
 * The screens, by the name a deck uses. `height` is the window's, where the
 * slide needs more than one screenful; `then` prepares the page; `areas`
 * measures what the slides point at, in CSS pixels.
 */
const SHOTS = [
  {
    name: "builder",
    path: (ids) => `/agents/${ids.agent}`,
    height: 1180,
    areas: async (page) => {
      const title = await box(page.locator("main h1"));
      const publish = await box(page.locator('[data-tour="agent-publish"]'));
      const tabs = await box(page.locator('[data-tour="agent-tab-build"]').locator(".."));
      return {
        header: { x: title.x, y: title.y, width: publish.x + publish.width - title.x, height: tabs.y - 16 - title.y },
        tabs,
        instructions: await box(page.locator('[data-tour="agent-instructions"]')),
        model: top(await box(page.locator('[data-tour="agent-model"]')), 150),
      };
    },
  },
  {
    name: "agents",
    path: () => "/agents",
    areas: async (page) => ({
      create: union(await box(page.locator('[data-tour="agents-templates"]')), await box(page.locator('[data-tour="agents-new"]'))),
      filters: await box(page.locator('[data-tour="agents-filters"]')),
      card: await box(card(page, "Finance Analyst")),
    }),
  },
  {
    name: "chat",
    path: (ids) => `/chat?id=${ids.conversation}`,
    // The thread opens at its end; the slide starts at the folded work above the
    // answer - the steps, the published app among them, fold away once a turn ends.
    then: async (page) =>
      page.getByText(/^Worked for/).first().evaluate((element) => {
        element.scrollIntoView({ block: "start" });
        let scroller = element.parentElement;
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;
        scroller?.scrollBy(0, -24);
      }),
    areas: async (page) => {
      const answer = union(
        await box(page.getByText("The dashboard is published and private", { exact: false })),
        await box(page.getByText(/^\d+ sources$/)),
      );
      // The folded work above the answer, as wide as the answer it led to.
      const steps = await box(page.getByText(/^Worked for/).first());
      return {
        steps: { ...steps, x: answer.x, width: answer.width },
        app: await box(card(page, "Ledgerly revenue dashboard - Jan to Sep 2026")),
        answer,
        composer: await box(page.locator('[data-tour="chat-composer"]')),
      };
    },
  },
  { name: "skills", path: () => "/skills", areas: async () => ({}) },
  {
    name: "skill-detail",
    path: () => "/skills",
    then: async (page) => page.getByText("month-end-close-checklist", { exact: true }).first().click(),
    areas: async (page) => {
      const dialog = page.getByRole("dialog");
      return {
        description: await box(dialog.getByText("Description", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded')][1]")),
        files: await box(dialog.getByText("SKILL.md", { exact: true }).first().locator("xpath=ancestor::*[contains(@class,'rounded') and contains(@class,'border')][1]")),
        content: await box(dialog.getByText("Running the month-end close", { exact: false }).locator("xpath=ancestor::*[contains(@class,'rounded') and contains(@class,'border')][1]")),
      };
    },
  },
  {
    name: "context",
    path: () => "/context",
    then: async (page) => page.getByText("Glossary", { exact: true }).first().click(),
    areas: async (page) => {
      const dialog = page.getByRole("dialog");
      return {
        mode: await box(dialog.getByText("Mode", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded')][1]")),
        content: await box(dialog.getByText("Glossary.md", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded') and contains(@class,'border')][1]")),
      };
    },
  },
  { name: "kb-list", path: () => "/rag", areas: async () => ({}) },
  {
    name: "kb-collection",
    path: (ids) => `/rag/${ids.collection}`,
    areas: async (page) => ({
      header: await box(page.locator('[data-tour="kb-header"]')),
      sync: await box(page.locator('[data-tour="kb-tab-sync"]')),
      documents: await box(page.locator('[data-tour="kb-documents"]')),
      actions: union(
        await box(page.getByRole("button", { name: "Add to an agent", exact: true })),
        await box(page.getByRole("button", { name: "Upload", exact: true })),
      ),
    }),
  },
  {
    name: "kb-parse",
    path: (ids) => `/rag/${ids.collection}`,
    then: async (page) => page.getByRole("button", { name: "Parse options", exact: true }).click(),
    areas: async (page) => ({ dialog: await box(page.getByRole("dialog")) }),
  },
  {
    name: "artifact",
    path: (ids) => `/apps/${ids.app}`,
    then: async (page) => page.waitForTimeout(4000),
    areas: async (page) => {
      const frame = await box(page.locator("iframe"));
      const bar = { x: 0, y: 0, width: WIDTH, height: frame.y };
      const inside = page.frameLocator("iframe");
      const offset = (b) => ({ ...b, x: b.x + frame.x, y: b.y + frame.y });
      const within = async (locator) => {
        const handle = await locator.first().elementHandle();
        const rect = await handle.evaluate((e) => {
          const r = e.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height };
        });
        return offset(rect);
      };
      return {
        bar,
        share: await box(page.getByRole("button", { name: "Share", exact: true })),
        numbers: await within(inside.getByText("September MRR", { exact: false }).locator("xpath=ancestor::*[count(*)>=4][1]")),
        chart: await within(inside.locator("canvas, svg").first().locator("xpath=..")),
        findings: union(
          await within(inside.getByText("Where churn hurts", { exact: true })),
          await within(inside.getByText("Where churn hurts", { exact: true }).locator("xpath=following-sibling::*[1]")),
        ),
      };
    },
  },
  { name: "artifacts", path: () => "/apps", areas: async () => ({}) },
  {
    name: "room",
    // A project chat several people work in: the plan, a teammate's reply, and the agent applying it.
    path: (ids) => `/chat?id=${ids.room}`,
    height: 1000,
    then: async (page) =>
      page.getByText("Questions for you", { exact: true }).first().evaluate((element) => {
        element.scrollIntoView({ block: "start" });
        let scroller = element.parentElement;
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;
        scroller?.scrollBy(0, -56);
      }),
    areas: async (page) => ({
      questions: union(await box(page.getByText("Questions for you", { exact: true }).first()), await box(page.getByText(/^Dates I assumed/).first().locator("xpath=ancestor::li[1]"))),
      reply: union(await box(page.getByText(/In reply to/).first()), await box(page.getByText(/^Peter confirmed/).first())),
      answer: top(await climb(page, "Budget changes", (r) => r.height > 80), 220),
      composer: await box(page.locator('[contenteditable="true"], textarea').first().locator("xpath=ancestor::*[contains(@class,'rounded')][1]")),
    }),
  },
  {
    name: "room-coding",
    // The same room after a teammate handed the launch page to the coding agent.
    path: (ids) => `/chat?id=${ids.room}`,
    height: 1000,
    then: async (page) =>
      page.getByText(/^Build the launch page from launch-plan/).first().evaluate((element) => {
        element.scrollIntoView({ block: "start" });
        let scroller = element.parentElement;
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;
        scroller?.scrollBy(0, -40);
      }),
    areas: async (page) => {
      // The answer's own column: its headings and labels are narrower than the text under them.
      const column = await box(page.getByText(/^Jordan, the launch page is built/).first());
      const wide = (b) => ({ ...b, x: column.x, width: column.width });
      return {
        request: await box(page.getByText(/^Build the launch page from launch-plan/).first()),
        page: wide(union(await box(page.getByText("What's on the page", { exact: true }).first()), await box(page.getByText(/^Layout:/).first().locator("xpath=ancestor::li[1]")))),
        decisions: wide(union(await box(page.getByText("Two decisions for you", { exact: true }).first()), await box(page.getByText(/^Sign-up link:/).first().locator("xpath=ancestor::li[1]")))),
        codex: await box(page.getByText(/Talked it through with Codex/).first()),
      };
    },
  },
  {
    name: "visual",
    // A drawing an agent made under its answer: an ROI calculator with sliders.
    path: (ids) => `/chat?id=${ids.visual}`,
    height: 1240,
    then: async (page) => {
      await page.getByText("Ledgerly Autopilot ROI calculator", { exact: true }).first().evaluate((element) => {
        element.scrollIntoView({ block: "start" });
        let scroller = element.parentElement;
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;
        scroller?.scrollBy(0, -150);
      });
      await page.waitForTimeout(2500);
    },
    areas: async (page) => {
      const frame = await box(page.locator("iframe").first());
      return {
        drawing: frame,
        tools: await box(page.getByText("Ledgerly Autopilot ROI calculator", { exact: true }).first().locator("xpath=ancestor::*[contains(@class,'rounded')][1]")),
        answer: union(await box(page.getByText(/^The calculator is on screen/).first()), await box(page.getByText(/^Look:/).first())),
      };
    },
  },
  {
    name: "channels",
    path: (ids) => `/agents/${ids.agent}`,
    then: async (page) => page.getByRole("tab", { name: "Availability", exact: true }).click(),
    areas: async (page) => ({
      surfaces: await box(card(page, "Where people reach this agent")),
      apps: await box(card(page, "Chat apps")),
    }),
  },
  {
    name: "triggers",
    path: () => "/routines",
    areas: async (page) => ({
      create: await box(page.locator('[data-tour="routines-create"]')),
      list: await box(page.locator('[data-tour="routines-list"]')),
      ideas: top(await box(page.locator('[data-tour="routines-ideas"]')), 330),
    }),
  },
  {
    name: "mcp",
    path: () => "/mcp-servers",
    areas: async (page) => ({
      filter: await box(page.locator('[data-tour="mcp-filter"]')),
      // The anchor is the catalog's header row now; the area runs from it down
      // the grid, to the bottom of the window.
      catalog: { ...(await box(page.locator('[data-tour="mcp-catalog"]'))), height: 900 - 160 },
      add: await box(page.locator('[data-tour="mcp-add"]')),
    }),
  },
  {
    name: "dashboard",
    path: () => "/dashboard?view=organization",
    height: 1150,
    then: async (page) => {
      const dismiss = page.getByText("Get started", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded')][1]").getByRole("button").last();
      if (await dismiss.count()) await dismiss.click().catch(() => {});
      await page.waitForTimeout(4000);
    },
    areas: async (page) => ({
      filters: await box(page.locator('[data-tour="dashboard-filters"]')),
      glance: await box(card(page, "This period at a glance")),
      trend: await box(card(page, "Runs over time")),
      outcomes: await box(card(page, "Outcomes")),
      waiting: top(await box(card(page, "Waiting on a decision")), 1150 - 760),
      failures: top(await box(card(page, "Recent failures")), 1150 - 760),
    }),
  },
  {
    name: "run-detail",
    path: () => "/runs",
    // Opening a run scrolls the page to its panel; the slide wants the page's top.
    then: async (page) => {
      // The support run whose answer the slide reads - searched for rather than
      // assumed first, since every later run pushes it down the list.
      // Narrowed to that agent, so the opened row stays in view beside its panel.
      await page.getByRole("combobox").filter({ hasText: "All agents" }).click();
      await page.getByRole("option", { name: "Support Desk" }).click();
      await page.waitForTimeout(1500);
      const rows = page.locator("table tbody tr", { hasText: "Support Desk" });
      for (let i = 0; i < (await rows.count()); i += 1) {
        await rows.nth(i).click();
        await page.waitForTimeout(1500);
        if (await page.getByText(/the support lead has to approve it/).count()) break;
      }
      // Clicking a lower row scrolls the page; the slide reads from its header.
      await page.evaluate(() => document.querySelectorAll("*").forEach((el) => { if (el.scrollTop && !el.closest("[role=dialog], aside")) el.scrollTop = 0; }));
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.locator("main h1").first().evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
    areas: async (page) => {
      const panel = await climb(page, "Open the chat this run happened in", (r) => r.height > 600);
      return {
        filters: await climb(page, "Last 30 days", (r) => r.width > 300),
        list: await box(page.locator("table")),
        detail: panel,
        // The panel's own, not the table's column of the same name.
        numbers: await climb(page, "Tokens", (r) => r.width > 450 && r.height < 120, { last: true }),
        answer: union(
          await box(page.getByText("Knowledge Base Search", { exact: false })),
          await box(page.getByText(/the support lead has to approve it/)),
        ),
      };
    },
  },
  {
    name: "spend",
    path: () => "/runs",
    then: async (page) => page.locator('[data-tour="activity-tab-spend"]').click(),
    areas: async (page) => ({
      totals: await climb(page, "Month to date", (r) => r.width > 900),
      agents: await box(card(page, "Where the money went")),
    }),
  },
  {
    name: "approvals",
    path: () => "/runs",
    then: async (page) => page.locator('[data-tour="activity-tab-approvals"]').click(),
    areas: async (page) => {
      const list = await box(card(page, "Approvals"));
      const first = await box(page.getByRole("button", { name: "Approve" }).first().locator("xpath=ancestor::*[contains(@class,'border-b') or contains(@class,'border-t') or self::li][1]"));
      return { tabs: await box(page.locator('[data-tour="activity-overview"]')), request: first, list };
    },
  },
  {
    name: "groups",
    path: () => "/groups",
    areas: async (page) => ({
      header: await box(page.locator("main h1").locator("xpath=ancestor::*[2]")),
      list: await box(page.locator('[data-tour="groups-list"]')),
      create: await box(page.locator('[data-tour="groups-new"]')),
    }),
  },
  {
    name: "roles",
    path: (ids) => `/orgs/${ids.org}/roles`,
    areas: async (page) => {
      const matrix = await box(page.getByText("Permission matrix", { exact: true }).locator("xpath=ancestor::*[contains(@class,'rounded')][1]"));
      return {
        header: await box(page.locator("main h1").locator("xpath=ancestor::*[2]")),
        matrix: top(matrix, 900 - matrix.y - 12),
        roles: top(matrix, 140),
      };
    },
  },
  {
    name: "vault",
    path: () => "/vault",
    areas: async (page) => ({
      keys: await box(page.locator('[data-tour="vault-keys"]')),
      create: await box(page.locator('[data-tour="vault-new"]')),
    }),
  },
  {
    name: "sandboxes",
    path: () => "/sandboxes",
    areas: async (page) => ({
      header: await box(page.locator("main h1").locator("xpath=ancestor::*[2]")),
      connections: await box(page.locator('[data-tour="sandboxes-connections"]')),
    }),
  },
];

/**
 * Figures the decks share with the README: `../assets/readme/render.mjs` draws them
 * from figures.html, and this copies the picture and measures the named parts of
 * its section there, the same way it measures a screen.
 */
const FIGURES = [
  {
    name: "integrations-hub",
    areas: {
      models: ".hub > .top",
      surfaces: ".hub .left > .tile:nth-child(1)",
      starts: ".hub .left > .tile:nth-child(2)",
      tools: ".hub > .right",
      documents: ".hub > .bottom",
    },
  },
];

async function figures(browser) {
  const readme = join(here, "../assets/readme");
  const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });
  await page.goto(`file://${join(readme, "figures.html")}`);
  await page.waitForSelector("body[data-ready]");
  for (const figure of FIGURES) {
    if (only.size > 0 && !only.has(figure.name)) continue;
    const section = page.locator(`section[data-figure="${figure.name}"]`);
    const whole = await box(section);
    const measured = {};
    for (const [key, selector] of Object.entries(figure.areas)) {
      const b = await box(section.locator(selector));
      measured[key] = [(b.x - whole.x) / whole.width, (b.y - whole.y) / whole.height, b.width / whole.width, b.height / whole.height].map(
        (n) => Math.round(n * 1000) / 1000,
      );
    }
    areas[figure.name] = measured;
    execFileSync("cp", [join(readme, `${figure.name}.webp`), join(media, `${figure.name}.webp`)]);
    console.log(`media/${figure.name}.webp`, Object.keys(measured).join(" "));
  }
  await page.close();
}

/** Ids the routes need, looked up so the script works on any deployment. */
async function lookUp(page) {
  const orgs = (await (await page.request.get(`${BASE}/api/orgs`)).json()).items;
  const org = orgs.find((item) => (ORG ? item.name === ORG : !item.is_personal)) ?? orgs[0];
  const get = async (path) =>
    (await page.request.get(`${BASE}/api${path}`, { headers: { "X-Organization-Id": org.id } })).json();
  const agents = (await get("/agents?limit=100")).items;
  const conversations = (await get("/conversations?limit=50")).items;
  const collections = (await get("/kb?limit=100")).items;
  const apps = (await get("/apps?limit=1")).items;
  return {
    org: org.id,
    agent: (agents.find((item) => item.name === (process.env.AGENT ?? "Finance Analyst")) ?? agents[0])?.id,
    conversation: (conversations.find((item) => item.title?.startsWith(process.env.CHAT ?? "Attached is")) ?? conversations[0])?.id,
    collection: (collections.find((item) => item.name === (process.env.COLLECTION ?? "Support handbook")) ?? collections[0])?.id,
    app: apps[0]?.id,
    room: conversations.find((item) => item.title?.startsWith(process.env.ROOM ?? "Draft the launch plan"))?.id,
    visual: conversations.find((item) => item.title?.startsWith(process.env.VISUAL ?? "Build an interactive ROI"))?.id,
  };
}

const inOrg = (path, org) => `${path}${path.includes("?") ? "&" : "?"}org=${org}`;

const areasFile = join(media, "areas.js");
/** The areas written by an earlier run, or none: read once, so nothing can change between a check and the read. */
function readAreas() {
  try {
    return JSON.parse(readFileSync(areasFile, "utf8").replace(/^[^{]*/, "").replace(/;\s*$/, ""));
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
}
const areas = readAreas();
const previews = PREVIEW ? mkdtempSync(join(tmpdir(), "deck-areas-")) : null;

const browser = await chromium.launch();
await figures(browser);
for (const shot of SHOTS) {
  if (only.size > 0 && !only.has(shot.name)) continue;
  const height = shot.height ?? 900;
  const context = await browser.newContext({ viewport: { width: WIDTH, height }, deviceScaleFactor: 2, colorScheme: "light" });
  await context.addInitScript(() => {
    try {
      localStorage.setItem("assistant-bubbles", JSON.stringify({ silenced: [], off: true, seenRun: null, docked: true }));
    } catch {}
  });
  const page = await context.newPage();
  await page.request.post(`${BASE}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const ids = await lookUp(page);
  try {
    await page.goto(`${BASE}${inOrg(shot.path(ids), ids.org)}`);
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2500);
    await page.addStyleTag({
      content: '[aria-label="Open Architect"], [data-tour="assistant-launcher"] { display: none !important; }',
    });
    await page.getByRole("button", { name: "Accept all" }).click({ timeout: 1000 }).catch(() => {});
    if (shot.then) {
      await shot.then(page);
      await page.waitForTimeout(2000);
    }
    const measured = await shot.areas(page);
    // Cut to the window: a list taller than the screen is outlined where it shows.
    const visible = (b) => {
      const x = Math.max(0, b.x), y = Math.max(0, b.y);
      return { x, y, width: Math.min(WIDTH, b.x + b.width) - x, height: Math.min(height, b.y + b.height) - y };
    };
    areas[shot.name] = Object.fromEntries(
      Object.entries(measured).map(([key, raw]) => {
        const b = visible(raw);
        return [key, [b.x / WIDTH, b.y / height, b.width / WIDTH, b.height / height].map((n) => Math.round(n * 1000) / 1000)];
      }),
    );
    const png = join(media, `${shot.name}.png`);
    await page.screenshot({ path: png });
    execFileSync("magick", [png, "-quality", "88", join(media, `${shot.name}.webp`)]);
    if (previews) {
      const draw = Object.values(measured).flatMap((b) => [
        "-draw",
        `rectangle ${b.x * 2},${b.y * 2} ${(b.x + b.width) * 2},${(b.y + b.height) * 2}`,
      ]);
      execFileSync("magick", [png, "-fill", "none", "-stroke", "#6A5AE0", "-strokewidth", "6", ...draw, "-resize", "50%", join(previews, `${shot.name}.png`)]);
    }
    execFileSync("rm", [png]);
    console.log(`media/${shot.name}.webp`, Object.keys(measured).join(" "));
  } catch (error) {
    console.error(`skipped ${shot.name}: ${error.message.split("\n")[0]}`);
  }
  await context.close();
}
await browser.close();

writeFileSync(
  areasFile,
  `// Written by capture.mjs - do not edit. Each screen's areas as [x, y, width, height] fractions.\nwindow.AREAS = ${JSON.stringify(areas, null, 1)};\n`,
);
if (previews) console.log(`areas drawn in ${previews}`);
