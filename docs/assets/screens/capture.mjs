/**
 * Capture every console screen the README and docs/screens.md show, in both themes.
 *
 *     node docs/assets/screens/capture.mjs                  # every screen, light and dark
 *     node docs/assets/screens/capture.mjs dashboard chat   # just these
 *     BASE_URL=http://localhost:3000 THEMES=light node docs/assets/screens/capture.mjs
 *     ORG="Northwind Labs" AGENT="Finance Analyst" CHAT="Attached is" node docs/assets/screens/capture.mjs
 *     ORG="Demo" AGENT="Refund desk" GAPS_AGENT="Refund desk (audit)" node docs/assets/screens/capture.mjs datasets improve-result
 *
 * Signs in as the seeded owner, walks the manifest below and writes
 * `<theme>/<name>.webp` beside this file: a 1600x1000 window at device scale 2,
 * downscaled to 1600 wide. Whatever the deployment holds is what the pictures
 * show, so run it against the demo data you want published. Ids the routes need
 * - an agent, a collection, a run - are looked up, never written here, so the
 * script works on any deployment. `ORG`, `AGENT` and `CHAT` choose which
 * organization, agent and conversation (by the start of its title) are shown;
 * left out, it is the first organization that is not a personal one, the
 * Claude Code like agent and the newest conversation with an agent in it. The
 * evals screens show that agent's largest dataset, newest eval run and newest
 * finished Improve session; `GAPS_AGENT` picks the agent whose knowledge gaps
 * are shown.
 *
 * Playwright and ImageMagick come from the developer's machine, like the README
 * figures beside it.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const VERSION = require("./package.json").version;
const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const EMAIL = process.env.OWNER_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.OWNER_PASSWORD ?? "admin123";
const THEMES = (process.env.THEMES ?? "light,dark").split(",");
const VIEW = { width: 1600, height: 1000 };
const only = new Set(process.argv.slice(2));
const ORG = process.env.ORG;
const AGENT = process.env.AGENT ?? "Claude Code like";
const CHAT = process.env.CHAT;
const HERO_CHAT = process.env.HERO_CHAT ?? "Revenue Pulse — six-month";
const GAPS_AGENT = process.env.GAPS_AGENT;

/** Open a tab of the page by its name. */
const tab = (name) => async (page) => {
  await page.getByRole("tab", { name, exact: true }).first().click();
};

/** Click whatever `selector` finds first. */
const click = (selector) => async (page) => {
  await page.locator(selector).first().click();
};

/** Press the button called `name`. */
const button = (name) => async (page) => {
  await page.getByRole("button", { name, exact: true }).first().click();
};

/** Open a tab, then scroll the page's section titled `title` to the top of the window. */
const scrollTo = (tabName, title) => async (page) => {
  await tab(tabName)(page);
  await page
    .locator("main")
    .getByText(title, { exact: true })
    .last()
    .evaluate((element) => element.scrollIntoView({ block: "start" }));
};

/** Open the first link on the page whose address starts with `prefix`. */
const first = (prefix) => async (page) => {
  await page.locator(`a[href^="${prefix}"]`).first().click();
};

/**
 * The screens, in the order docs/screens.md describes them. `path` may be a
 * function of the ids looked up at the start; `then` runs on the page before the
 * picture is taken.
 */
const SCREENS = [
  { name: "dashboard", path: "/dashboard?view=org", then: dismissChecklist },
  { name: "chat", path: (ids) => `/chat?id=${ids.conversation}`, then: framePreparedKit },
  // The README's first picture: a thread where the agent asked before it charted.
  {
    name: "chat-hero",
    path: (ids) => `/chat?id=${ids.hero}`,
    height: 1100,
    then: async (page) => {
      await page.frameLocator("iframe").first().getByRole("heading", { name: "Sales performance" }).waitFor();
      await page.locator("[data-message-id]").first().evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
  },
  { name: "agents", path: "/agents" },
  { name: "agent-templates", path: "/agents", then: button("Agent templates") },
  { name: "skills", path: "/skills" },
  { name: "skill-gallery", path: "/skills", then: button("Skill gallery") },
  {
    name: "skill-detail",
    path: "/skills",
    then: click('[data-tour="skills-list"] .peek-card > button'),
  },
  { name: "context", path: "/context" },
  { name: "agent-builder", path: (ids) => `/agents/${ids.agent}` },
  {
    name: "agent-toolbox",
    path: (ids) => `/agents/${ids.agent}`,
    then: tab("Toolbox"),
  },
  {
    name: "agent-mcp",
    path: (ids) => `/agents/${ids.agent}`,
    then: tab("MCP servers"),
  },
  {
    name: "agent-limits",
    path: (ids) => `/agents/${ids.agent}`,
    then: tab("Limits"),
  },
  {
    name: "agent-availability",
    path: (ids) => `/agents/${ids.agent}`,
    then: tab("Availability"),
  },
  {
    name: "agent-routines",
    path: (ids) => `/agents/${ids.agent}`,
    then: scrollTo("Availability", "Routines"),
  },
  {
    name: "agent-history",
    path: (ids) => `/agents/${ids.agent}`,
    then: tab("History"),
  },
  {
    name: "agent-map",
    path: (ids) => `/agents/${ids.agent}`,
    then: button("Visual map"),
  },
  { name: "workflows", path: "/workflows" },
  {
    name: "workflow-editor",
    path: (ids) => `/workflows/${ids.workflow}`,
    width: 2200,
    height: 1375,
  },
  {
    name: "workflow-documents",
    path: (ids) => `/workflows/${ids.documentsWorkflow}`,
  },
  {
    name: "workflow-support",
    path: (ids) => `/workflows/${ids.supportWorkflow}`,
  },
  {
    name: "workflow-loop-body",
    path: (ids) => `/workflows/${ids.loop}`,
    then: button("Open the body of For each company"),
  },
  { name: "workflow-runs", path: (ids) => `/workflows/${ids.loop}/runs` },
  {
    name: "workflow-run",
    height: 1600,
    path: (ids) => `/workflows/${ids.loop}/runs/${ids.workflowRun}`,
  },
  { name: "tables", path: "/tables" },
  {
    name: "table-detail",
    path: (ids) => `/tables/${ids.table}`,
    width: 1800,
    height: 1125,
  },
  {
    name: "table-kanban",
    path: (ids) => `/tables/${ids.table}?view=kanban&viewId=${ids.kanban}`,
  },
  { name: "mcp-server", path: "/settings/mcp" },
  { name: "knowledge-bases", path: "/rag" },
  { name: "knowledge-collection", path: "/rag", then: first("/rag/") },
  {
    name: "kb-parse-options",
    path: "/rag",
    then: async (page) => {
      await first("/rag/")(page);
      await button("Parse options")(page);
    },
  },
  { name: "datasets", path: "/datasets" },
  { name: "dataset-cases", path: (ids) => `/datasets/${ids.dataset}` },
  { name: "dataset-grading", path: (ids) => `/datasets/${ids.dataset}?tab=grading` },
  { name: "dataset-evals", path: (ids) => `/datasets/${ids.dataset}?tab=evals` },
  { name: "eval-run", path: (ids) => `/agents/${ids.agent}/evals/${ids.evalRun}` },
  { name: "agent-evals", path: (ids) => `/agents/${ids.agent}?tab=evals` },
  { name: "improve-start", path: (ids) => `/agents/${ids.agent}/improve/new` },
  {
    name: "improve-understand",
    path: (ids) => `/agents/${ids.agent}/improve/${ids.improvement}?step=understand`,
  },
  { name: "improve-changes", path: (ids) => `/agents/${ids.agent}/improve/${ids.improvement}?step=changes` },
  { name: "improve-result", path: (ids) => `/agents/${ids.agent}/improve/${ids.improvement}?step=result` },
  { name: "knowledge-gaps", path: (ids) => `/agents/${ids.gapsAgent}?tab=gaps` },
  {
    name: "ai-assistance",
    path: (ids) => `/orgs/${ids.org}/members?tab=governance`,
    then: async (page) => {
      await page
        .locator("main")
        .getByRole("heading", { name: "AI assistance", exact: true })
        .evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
  },
  { name: "documents", path: "/documents" },
  { name: "activity", path: "/runs" },
  { name: "run-detail", path: "/runs", then: click("table tbody tr") },
  {
    name: "approvals",
    path: "/runs",
    then: click('[data-tour="activity-tab-approvals"]'),
  },
  {
    name: "spend",
    path: "/runs",
    then: click('[data-tour="activity-tab-spend"]'),
  },
  { name: "routines", path: "/routines" },
  {
    name: "routine-event-trigger",
    path: "/routines",
    then: button("New event trigger"),
  },
  { name: "apps", path: "/apps" },
  { name: "app-detail", path: (ids) => `/apps/${ids.app}` },
  { name: "app-launch", path: (ids) => `/apps/${ids.launchApp}` },
  { name: "app-shopping", path: (ids) => `/apps/${ids.shoppingApp}` },
  { name: "app-manufacturing", height: 1150, path: (ids) => `/apps/${ids.manufacturingApp}` },
  { name: "app-motor", height: 1150, path: (ids) => `/apps/${ids.motorApp}` },
  { name: "app-revenue", height: 1150, path: (ids) => `/apps/${ids.revenueApp}` },
  { name: "app-kit", path: (ids) => `/apps/${ids.kitApp}` },
  { name: "visuals", path: (ids) => `/chat?id=${ids.visualConversation}` },
  { name: "groups", path: "/groups" },
  { name: "organizations", path: "/orgs" },
  { name: "members", path: (ids) => `/orgs/${ids.org}/members` },
  { name: "roles", path: (ids) => `/orgs/${ids.org}/roles` },
  { name: "vault", path: "/vault" },
  { name: "mcp-servers", path: "/mcp-servers" },
  { name: "channels", path: "/channels" },
  { name: "sandboxes", path: "/sandboxes" },
  { name: "settings", path: "/settings/profile" },
  { name: "admin-users", path: "/admin/users" },
  { name: "admin-organizations", path: "/admin/organizations" },
  { name: "admin-system", path: "/admin/system" },
  { name: "admin-deployment", path: "/admin/settings" },
];

/** Frame the prepared kit walkthrough after its real Visuals iframe has settled. */
async function framePreparedKit(page) {
  if (!(await page.getByText("Trail Supply — Kit Studio", { exact: true }).count())) return false;
  await page.frameLocator("iframe").first().getByRole("button", { name: "Review this kit" }).waitFor();
  const messages = page.locator("[data-message-id]");
  const count = await messages.count();
  if (count < 2) return false;
  await messages.nth(count - 2).evaluate((element) => element.scrollIntoView({ block: "start" }));
  await page.mouse.move(1490, 500);
  await page.mouse.wheel(0, -50);
  return true;
}

/** The setup checklist is for a new deployment, not the picture of one in use. */
async function dismissChecklist(page) {
  const dismiss = page.getByRole("button", {
    name: "Hide the checklist",
    exact: true,
  });
  if (await dismiss.isVisible()) await dismiss.click();
}

/**
 * What the routes need from this deployment: the organization, an agent, a
 * conversation, an app, and the agent's largest dataset, newest eval run and
 * newest finished Improve session.
 */
async function lookUp(page) {
  const orgs = (await (await page.request.get(`${BASE}/api/orgs`)).json()).items;
  const org = orgs.find((item) => (ORG ? item.name === ORG : !item.is_personal)) ?? orgs[0];
  const get = async (path) =>
    (
      await page.request.get(`${BASE}/api${path}`, {
        headers: { "X-Organization-Id": org.id },
      })
    ).json();
  const agents = (await get("/agents?limit=100")).items;
  const agent = agents.find((item) => item.name === AGENT) ?? agents[0];
  const conversations = (await get("/conversations?limit=50")).items;
  const conversation =
    conversations.find((item) => (CHAT ? item.title?.startsWith(CHAT) : item.agents?.length)) ??
    conversations[0];
  const apps = (await get("/apps?limit=100")).items;
  const hero = conversations.find((item) => item.title?.startsWith(HERO_CHAT)) ?? conversation;
  const datasets = agent ? (await get(`/datasets?agent=${agent.id}&limit=20`)).items : [];
  datasets.sort((a, b) => b.case_count - a.case_count);
  const runs = agent ? (await get(`/agents/${agent.id}/eval-runs?skip=0&limit=1`)).items : [];
  const sessions = agent ? await get(`/agents/${agent.id}/improvements`) : [];
  const finished = sessions.find((item) => ["published", "accepted"].includes(item.status)) ?? sessions[0];
  const gapsAgent = agents.find((item) => item.name === GAPS_AGENT) ?? agent;
  const workflows = (await get("/workflows")).items;
  const tables = (await get("/tables")).items;
  const table = tables.find((item) => item.name === "Revenue pipeline · demo data") ?? tables[0];
  const views = table ? (await get(`/tables/${table.id}/views`)).items : [];
  const loop = workflows.find((item) => item.name === "Batch processing · local demo");
  return {
    agent: agent?.id,
    conversation: conversation?.id,
    hero: hero?.id,
    org: org.id,
    dataset: datasets[0]?.id,
    evalRun: runs[0]?.id,
    improvement: finished?.id,
    gapsAgent: gapsAgent?.id,
    app: (apps.find((item) => item.name === "demo-company-brain") ?? apps[0])?.id,
    launchApp: apps.find((item) => item.name === "demo-launch-room")?.id,
    shoppingApp: apps.find((item) => item.name === "demo-trail-supply")?.id,
    manufacturingApp: apps.find((item) => item.name === "demo-northline-operations")?.id,
    motorApp: apps.find((item) => item.name === "demo-motor-atlas")?.id,
    revenueApp: apps.find((item) => item.name === "demo-revenue-pulse")?.id,
    kitApp: apps.find((item) => item.name === "demo-trail-supply-kit")?.id,
    visualConversation: conversations.find((item) =>
      item.title?.startsWith("Seeded demo · Visuals"),
    )?.id,
    workflow: workflows.find((item) => item.name.startsWith("Revenue operations"))?.id,
    documentsWorkflow: workflows.find((item) => item.name.startsWith("Document intelligence"))?.id,
    supportWorkflow: workflows.find((item) => item.name.startsWith("Customer support"))?.id,
    loop: loop?.id,
    workflowRun: loop?.last_run?.id,
    table: table?.id,
    kanban: views.find((item) => item.kind === "kanban")?.id,
  };
}

/** The address, in the organization chosen: the console adopts `?org=` on arrival. */
function inOrg(path, org) {
  return `${path}${path.includes("?") ? "&" : "?"}org=${org}`;
}

/** The console's own chrome that is not the screen: the Architect's corner, the cookie note. */
async function tidy(page) {
  await page.addStyleTag({
    content:
      '[aria-label="Open Architect"], [data-tour="assistant-launcher"] { display: none !important; }',
  });
  await page
    .getByRole("button", { name: "Accept all" })
    .click({ timeout: 1000 })
    .catch(() => {});
}

const failures = [];
const scratch = mkdtempSync(join(tmpdir(), "console-screens-"));
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL ?? "chrome",
});
for (const theme of THEMES) {
  mkdirSync(join(here, theme), { recursive: true });
  const context = await browser.newContext({
    viewport: VIEW,
    deviceScaleFactor: 2,
    colorScheme: theme,
  });
  await context.addInitScript(() => {
    if (window.top !== window) return;
    try {
      localStorage.setItem(
        "assistant-bubbles",
        JSON.stringify({
          silenced: [],
          off: true,
          seenRun: null,
          docked: true,
        }),
      );
    } catch {}
  });
  await context.addInitScript((chosen) => { if (window.top === window) localStorage.setItem("theme", chosen); }, theme);
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(60000);
  await page.request.post(`${BASE}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  const ids = await lookUp(page);
  const identityResponse = await page.request.get(`${BASE}/api/auth/me`);
  if (!identityResponse.ok()) throw new Error("The demo owner could not sign in");
  const { access_token: _accessToken, ...user } = await identityResponse.json();
  await context.addInitScript(
    ({ user, org, version }) => {
      if (window.top !== window) return;
      localStorage.setItem(
        "release-notes",
        JSON.stringify({
          state: { acknowledged: { [user.id]: version } },
          version: 0,
        }),
      );
      localStorage.setItem(
        "auth-storage",
        JSON.stringify({
          state: { user, isAuthenticated: true, sessionOwnerId: user.id },
          version: 0,
        }),
      );
      localStorage.setItem(
        "org-storage",
        JSON.stringify({ state: { activeOrgId: org }, version: 0 }),
      );
    },
    { user, org: ids.org, version: VERSION },
  );
  for (const screen of SCREENS) {
    if (only.size > 0 && !only.has(screen.name)) continue;
    const path = typeof screen.path === "function" ? screen.path(ids) : screen.path;
    try {
      await page.setViewportSize({
        width: screen.width ?? VIEW.width,
        height: screen.height ?? VIEW.height,
      });
      await page.goto(`${BASE}${inOrg(path, ids.org)}`);
      await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
      await page.locator("main").first().waitFor({ timeout: 30000 });
      await page
        .getByText("Checking authentication...", { exact: true })
        .waitFor({ state: "hidden", timeout: 30000 });
      const releaseNotice = page.getByRole("button", {
        name: "Got it",
        exact: true,
      });
      if (await releaseNotice.isVisible()) await releaseNotice.click();
      await tidy(page);
      if (screen.then) {
        await screen.then(page);
        await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
      }
      if (screen.name === "workflow-run") {
        const fit = page.locator(".react-flow__controls-fitview");
        if (await fit.isVisible()) {
          await fit.click();
          await page.waitForTimeout(500);
        }
        await page.evaluate(() => {
          window.scrollTo(0, 0);
          for (const el of document.querySelectorAll("*")) if (el.scrollTop > 0) el.scrollTop = 0;
        });
      }
      if (screen.name === "visuals")
        await page
          .frameLocator("iframe")
          .first()
          .getByRole("button", {
            name: "Who approves this invoice?",
            exact: true,
          })
          .waitFor();
      // Let entrance transitions and skeletons settle.
      await page.waitForTimeout(1500);
      const png = join(scratch, `${theme}-${screen.name}.png`);
      await page.screenshot({ path: png });
      execFileSync("magick", [
        png,
        "-filter",
        "Lanczos",
        "-resize",
        "1600x",
        "-quality",
        "86",
        join(here, theme, `${screen.name}.webp`),
      ]);
      console.log(`${theme}/${screen.name}.webp`);
    } catch (error) {
      failures.push(`${theme}/${screen.name}`);
      console.error(`skipped ${theme}/${screen.name}: ${error.message.split("\n")[0]}`);
    }
  }
  await context.close();
}
await browser.close();
if (failures.length > 0) {
  console.error(`Failed captures: ${failures.join(", ")}`);
  process.exitCode = 1;
}
