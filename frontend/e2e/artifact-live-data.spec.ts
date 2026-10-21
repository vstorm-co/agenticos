import type {
  APIRequestContext,
  APIResponse,
  Browser,
  BrowserContext,
  FrameLocator,
  Page,
  Response,
} from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  COLLEAGUE_PASSWORD,
  FAKE_KEY_LABEL,
  LIVE_CLOSED_RECORD_TITLE,
  LIVE_RECORD_TITLE,
  LIVE_TABLE_NAME,
  LIVE_VIEW_NAME,
  STUB_MODEL_ENDPOINT,
  json,
  nowMatching,
  rowsAt,
  signInAs,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * A page bound to a saved view, from the run that publishes it to the viewer
 * that refreshes it - and to everyone who must not get its records.
 *
 * Nothing here is set up by writing an artifact row: an agent publishes the
 * page through a real run, the stub model calling `publish_artifact` with the
 * page and its bindings this spec spelled out (`CALL-TOOL` in
 * `stub-model-server.ts`). So the binding the console reads is one the
 * capability resolved against the agent's own table grant and the view the
 * seed shared.
 *
 * **What is asserted is inside the page**, because the strip around it renders
 * the same whether or not a record ever crossed: `#state` is what the page's
 * own `agenticos.onData` was handed, `#rows` the titles it drew, and `#load` a
 * random id the document picks once per load - unchanged after Refresh is the
 * proof the page was updated in place rather than loaded again.
 *
 * Every page also asks for `https://example.invalid/beacon`, which the content
 * policy refuses. That refusal is the canary for the CSP collector: it shows
 * the collector reports a violation from the framed page, so "nothing else was
 * refused" - a console `frame-src` that stopped allowing the page, say - is an
 * assertion that can fail.
 */

/** Long enough for the two runs and the polls behind them, on a dev server that compiles. */
const SETUP_TIMEOUT = 180_000;

/** The binding the page declares, and the two fields it reads. */
const BINDING = "tickets";

/** Where a page's live data is read, through the console's proxy. */
const DATA_PATH = /\/api\/artifacts\/[^/]+\/versions\/[^/]+\/data$/;
/** Where a frame's signed address is minted. A second one after Refresh is a reload. */
const VIEW_PATH = /\/api\/artifacts\/[^/]+\/view$/;
/** The violation every load of the page produces, and the only one allowed. */
const CANARY = /^CSP-VIOLATION img-src https:\/\/example\.invalid\/beacon/;

/**
 * The page the agent publishes. `marker` tells v1 from v2.
 *
 * Records go in with `textContent`, as the tool's own docstring tells an agent:
 * a title is table data and never markup.
 */
function pageHtml(marker: string): string {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Live tickets</title></head>
<body>
<p id="marker">${marker}</p>
<p>Load <span id="load"></span></p>
<p>State <span id="state">waiting</span></p>
<ul id="rows"></ul>
<script>
document.getElementById("load").textContent = Math.random().toString(36).slice(2);
new Image().src = "https://example.invalid/beacon";
agenticos.onData(function (data) {
  var binding = data.${BINDING};
  document.getElementById("state").textContent = binding.status;
  var rows = document.getElementById("rows");
  rows.textContent = "";
  binding.records.forEach(function (record) {
    var item = document.createElement("li");
    item.textContent = record.title;
    rows.appendChild(item);
  });
});
</script>
</body></html>`;
}

/** The prompt that makes the stub call `publish_artifact` with exactly these arguments. */
function publishPrompt(args: Record<string, unknown>): string {
  const encoded = Buffer.from(JSON.stringify(args), "utf8").toString("base64url");
  return `Publish the page. CALL-TOOL:publish_artifact:${encoded}`;
}

/**
 * Report every CSP violation in every frame of this context's pages as a console
 * error, so `collectViolations` can read them.
 *
 * An init script reaches the sandboxed content frame too: Playwright injects it
 * into each frame, past the frame's own policy.
 */
async function reportViolations(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.error(
        `CSP-VIOLATION ${event.violatedDirective} ${event.blockedURI} in ${event.documentURI}`,
      );
    });
  });
}

/**
 * One violation, and the document it came from - read off the event rather
 * than the console message, whose location is empty for an opaque-origin frame.
 */
interface Violation {
  text: string;
  url: string;
}

function collectViolations(page: Page): Violation[] {
  const violations: Violation[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (!text.startsWith("CSP-VIOLATION")) return;
    violations.push({ text, url: text.split(" in ").pop() ?? "" });
  });
  return violations;
}

/**
 * The canary was refused, from the framed page, and nothing else was.
 *
 * Polled, because the console message arrives on its own schedule after the
 * page has drawn.
 */
async function expectOnlyTheCanary(violations: Violation[]): Promise<void> {
  await expect
    .poll(() => violations.length, {
      message: "the page's canary image was never refused, so the CSP collector saw nothing",
    })
    .toBeGreaterThan(0);
  for (const violation of violations) {
    expect(violation.text, `an unexpected CSP violation at ${violation.url}`).toMatch(CANARY);
    expect(violation.url, "the canary was refused somewhere other than the framed page").toContain(
      "/artifact-content/",
    );
  }
}

/** What every page this test opened was refused, checked once it has finished. */
let watched: Violation[][] = [];

/** Collect `page`'s CSP violations for the check after the test, before it navigates. */
async function watch(page: Page): Promise<void> {
  await reportViolations(page.context());
  watched.push(collectViolations(page));
}

/** The framed page in the viewer, by the title the frame carries. */
function framedPage(page: Page, title: string): FrameLocator {
  return page.locator(`iframe[title="${title}"]`).first().contentFrame();
}

function isData(response: Response): boolean {
  return DATA_PATH.test(new URL(response.url()).pathname);
}

/** Everything the spec made, by id, for the tests and for the teardown. */
interface Fixture {
  stamp: string;
  title: string;
  artifactId: string;
  v1Id: string;
  tableId: string;
  titleColumnId: string;
  recordId: string;
  agentId: string;
  profileId: string;
  colleagueId: string;
}

let fixture: Fixture;
let owner: BrowserContext | undefined;

async function ownerRequest(browser: Browser): Promise<APIRequestContext> {
  owner ??= await browser.newContext({ storageState: AUTH_STATE });
  return owner.request;
}

/** A 2xx, or a failure that says what the API answered. */
async function ok(response: APIResponse, what: string): Promise<void> {
  if (!response.ok()) {
    expect(response.ok(), `${what} answered ${response.status()}: ${await response.text()}`).toBe(
      true,
    );
  }
}

/** One record of the live table, as the API answers it. */
interface LiveRecord {
  id: string;
  revision: number;
  values: Record<string, unknown>;
}

async function liveRecord(request: APIRequestContext): Promise<LiveRecord> {
  return json<LiveRecord>(request, `/api/tables/${fixture.tableId}/records/${fixture.recordId}`);
}

/** Retitle the seeded record, and wait until the API reads it back. */
async function retitle(request: APIRequestContext, title: string): Promise<void> {
  const current = await liveRecord(request);
  if (current.values[fixture.titleColumnId] === title) return;
  await ok(
    await request.patch(`/api/tables/${fixture.tableId}/records/${fixture.recordId}`, {
      data: { expected_revision: current.revision, values: { [fixture.titleColumnId]: title } },
    }),
    "retitling the record",
  );
  await expect
    .poll(async () => (await liveRecord(request)).values[fixture.titleColumnId])
    .toBe(title);
}

test.describe("artifact live data", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(SETUP_TIMEOUT);
    const request = await ownerRequest(browser);
    const stamp = Date.now().toString(36);
    const title = `E2E Live ${stamp}`;

    // What the seed left: the table, its shared view, the record, the colleague.
    const table = (await rowsAt(request, "/api/tables")).find(
      (row) => row.name === LIVE_TABLE_NAME,
    );
    expect(table, `no table is named ${LIVE_TABLE_NAME}; did the seed run?`).toBeDefined();
    const tableId = String(table!.id);
    const view = (await rowsAt(request, `/api/tables/${tableId}/views`)).find(
      (row) => row.name === LIVE_VIEW_NAME,
    );
    expect(view, `${LIVE_TABLE_NAME} has no view named ${LIVE_VIEW_NAME}`).toBeDefined();
    const { columns } = await json<{ columns: { id: string; label: string }[] }>(
      request,
      `/api/tables/${tableId}`,
    );
    const titleColumnId = columns.find((column) => column.label === "Title")!.id;
    const record = (await rowsAt(request, `/api/tables/${tableId}/records`)).find(
      (row) => (row.values as Record<string, unknown>)[titleColumnId] === LIVE_RECORD_TITLE,
    );
    expect(record, `no record of ${LIVE_TABLE_NAME} is titled ${LIVE_RECORD_TITLE}`).toBeDefined();
    const orgs = await json<{ items: { id: string }[] }>(request, "/api/orgs");
    const colleague = (await rowsAt(request, `/api/orgs/${orgs.items[0]!.id}/members`)).find(
      (row) => row.email === COLLEAGUE_EMAIL,
    );
    expect(colleague, "the colleague is not a member; did the seed run?").toBeDefined();

    // A model on the stub, keyed by the seed's provider key - the stub checks none.
    const key = (await rowsAt(request, "/api/secrets")).find((row) => row.name === FAKE_KEY_LABEL);
    expect(key, `no secret is named ${FAKE_KEY_LABEL}`).toBeDefined();
    const profile = await request.post("/api/providers/model-profiles", {
      data: {
        label: `e2e-live-model-${stamp}`,
        provider: "openai",
        model: "gpt-4.1-mini",
        secret_id: key!.id,
        base_url: STUB_MODEL_ENDPOINT,
      },
    });
    await ok(profile, "creating the stub model profile");
    // Recorded as soon as each row exists, so the teardown removes what a failed
    // setup did create.
    fixture = {
      stamp,
      title,
      artifactId: "",
      v1Id: "",
      tableId,
      titleColumnId,
      recordId: String(record!.id),
      agentId: "",
      profileId: ((await profile.json()) as { id: string }).id,
      colleagueId: String(colleague!.user_id),
    };

    // The agent: Artifacts to publish, and read on the one table its page binds.
    const spec = {
      name: `E2E Live Publisher ${stamp}`,
      instructions: "You are an E2E fixture. Do what the message says.",
      model_profile_id: fixture.profileId,
      capabilities: [
        { id: "artifacts" },
        {
          id: "virtual_tables",
          config: { tables: [{ table_id: tableId, operations: ["read"] }] },
        },
      ],
    };
    const created = await request.post("/api/agents", {
      data: { spec: { name: spec.name } },
    });
    await ok(created, "creating the agent");
    const agentId = ((await created.json()) as { id: string }).id;
    fixture.agentId = agentId;
    await ok(await request.put(`/api/agents/${agentId}/draft`, { data: { spec } }), "the draft");
    await ok(await request.post(`/api/agents/${agentId}/publish`, { data: {} }), "publishing");

    // Two runs, one version each. The signed-in owner is the person behind them,
    // which is what lets a run bind a page to live data at all.
    const name = `e2e-live-${stamp}`;
    for (const marker of ["v1", "v2"]) {
      const run = await request.post(`/api/agents/${agentId}/run`, {
        data: {
          prompt: publishPrompt({
            name,
            title,
            content: pageHtml(marker),
            bindings: {
              [BINDING]: { view: view!.id, fields: { title: "Title", status: "Status" } },
            },
          }),
        },
        timeout: SETUP_TIMEOUT,
      });
      await ok(run, `the ${marker} run`);
      const listed = await nowMatching(
        request,
        `/api/artifacts?q=${encodeURIComponent(title)}`,
        (row) =>
          row.title === title &&
          (row.current_version as { number: number } | null)?.number === (marker === "v1" ? 1 : 2),
        `an artifact titled ${title} at version ${marker}`,
      );
      fixture.artifactId = String(listed.id);
    }
    const versions = await rowsAt(request, `/api/artifacts/${fixture.artifactId}/versions`);
    fixture.v1Id = String(versions.find((version) => version.number === 1)!.id);
  });

  test.afterAll(async ({ browser }) => {
    const request = await ownerRequest(browser);
    if (fixture !== undefined) {
      await retitle(request, LIVE_RECORD_TITLE);
      // In dependency order, as `delegation.spec.ts` does: the artifact names the
      // agent, the agent the profile.
      const paths = [
        fixture.artifactId && `/api/artifacts/${fixture.artifactId}`,
        fixture.agentId && `/api/agents/${fixture.agentId}`,
        `/api/providers/model-profiles/${fixture.profileId}`,
      ].filter(Boolean);
      for (const path of paths) {
        const removed = await request.delete(path);
        expect(removed.ok(), `${path} answered ${removed.status()} at teardown`).toBe(true);
      }
    }
    await owner?.close();
  });

  // After each test rather than at its end, so a test that already failed - a
  // frame the console's own policy refused never draws - still reports what was
  // refused, and that is the line that names the cause.
  test.afterEach(async () => {
    const pages = watched;
    watched = [];
    for (const violations of pages) await expectOnlyTheCanary(violations);
  });

  test("the current version shows the view's records", async ({ page }) => {
    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);

    const frame = framedPage(page, fixture.title);
    await expect(frame.locator("#marker")).toHaveText("v2");
    await expect(frame.locator("#state")).toHaveText("ok");
    await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);
    // The view's filter reached the read: the closed record is in the table, not the view.
    await expect(frame.locator("#rows")).not.toContainText(LIVE_CLOSED_RECORD_TITLE);

    await expect(page.locator("header").getByText("Live", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh", exact: true })).toHaveAttribute(
      "title",
      /^Updated /,
    );
  });

  test("Refresh updates the page in place", async ({ page }) => {
    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);
    const frame = framedPage(page, fixture.title);
    await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);
    const load = await frame.locator("#load").textContent();
    expect(load, "the page never set its load id").toBeTruthy();

    const renamed = `E2E-LIVE-${fixture.stamp.toUpperCase()}`;
    await retitle(page.request, renamed);

    const views: string[] = [];
    page.on("response", (response) => {
      if (VIEW_PATH.test(new URL(response.url()).pathname)) views.push(response.url());
    });
    const read = page.waitForResponse(isData);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    expect((await read).ok(), "the refresh's read failed").toBe(true);

    await expect(frame.locator("#rows")).toContainText(renamed);
    await expect(frame.locator("#rows")).not.toContainText(LIVE_RECORD_TITLE);
    await expect(frame.locator("#load"), "Refresh reloaded the page").toHaveText(load!);
    expect(views, "Refresh minted a new address for the frame, so it reloaded").toEqual([]);
  });

  test("auto-refresh fetches on its interval and remembers the choice", async ({ page }) => {
    await watch(page);
    await page.clock.install();
    await page.goto(`/artifacts/${fixture.artifactId}`);
    await expect(framedPage(page, fixture.title).locator("#state")).toHaveText("ok");

    const menu = page.getByRole("button", { name: "Refresh automatically" });
    await menu.click();
    await page.getByRole("menuitemradio", { name: "Every minute" }).click();

    const reads: string[] = [];
    page.on("response", (response) => {
      if (isData(response)) reads.push(response.url());
    });
    await page.clock.runFor(61_000);
    await expect
      .poll(() => reads.length, { message: "a minute passed and the page was not read again" })
      .toBe(1);

    await page.reload();
    await expect(framedPage(page, fixture.title).locator("#state")).toHaveText("ok");
    await menu.click();
    await expect(page.getByRole("menuitemradio", { name: "Every minute" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await page.getByRole("menuitemradio", { name: "Off" }).click();
  });

  test("a member without the table sees unavailable", async ({ page, browser }) => {
    // Shared at the lowest level: the page opens for the colleague, and the
    // table behind it stays the owner's.
    await ok(
      await page.request.put(`/api/artifacts/${fixture.artifactId}/sharing/grants`, {
        data: { subject_user_id: fixture.colleagueId, level: "read" },
      }),
      "sharing the artifact with the colleague",
    );

    const context = await signInAs(browser, COLLEAGUE_EMAIL, COLLEAGUE_PASSWORD);
    try {
      const colleague = await context.newPage();
      await watch(colleague);
      const failures: string[] = [];
      colleague.on("response", (response) => {
        if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
      });
      await colleague.goto(`/artifacts/${fixture.artifactId}`);

      const frame = framedPage(colleague, fixture.title);
      await expect(frame.locator("#state")).toHaveText("unavailable");
      await expect(frame.locator("#rows")).not.toContainText(LIVE_RECORD_TITLE);
      await expect(colleague.getByText("1 of 1 sources unavailable to you.")).toBeVisible();
      // A reader is told how many, never why: the cause is for an editor.
      await expect(colleague.getByRole("link", { name: "Open the table" })).toHaveCount(0);
      expect(failures).toEqual([]);
    } finally {
      await context.close();
    }
  });

  test("an older version gets no data", async ({ page }) => {
    await watch(page);
    const reads: string[] = [];
    page.on("request", (request) => {
      if (DATA_PATH.test(new URL(request.url()).pathname)) reads.push(request.url());
    });
    await page.goto(`/artifacts/${fixture.artifactId}?version=${fixture.v1Id}`);

    const frame = framedPage(page, fixture.title);
    await expect(frame.locator("#marker")).toHaveText("v1");
    await expect(page.getByText("Live data only on the current version.")).toBeVisible();
    await expect(frame.locator("#state")).toHaveText("unavailable");
    await expect(frame.locator("#rows")).toBeEmpty();
    expect(reads, "an older version's page read live data").toEqual([]);

    await page.getByRole("button", { name: "Open current" }).click();
    await expect(frame.locator("#marker")).toHaveText("v2");
    await expect(frame.locator("#state")).toHaveText("ok");
    await expect(page.getByText("Live data only on the current version.")).toHaveCount(0);
  });

  test("a public link carries no data", async ({ page, browser }) => {
    const linked = await page.request.put(`/api/artifacts/${fixture.artifactId}/public-link`);
    await ok(linked, "turning the public link on");
    const { public_url: publicUrl } = (await linked.json()) as { public_url: string | null };
    expect(publicUrl, "the public link answered without an address").toBeTruthy();

    const stranger = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    try {
      const visitor = await stranger.newPage();
      await watch(visitor);
      const reads: string[] = [];
      visitor.on("request", (request) => {
        if (/\/versions\/.+\/data/.test(new URL(request.url()).pathname)) {
          reads.push(request.url());
        }
      });
      const content = visitor.waitForResponse(
        (response) =>
          response.url().includes("/artifact-content/") &&
          !response.url().includes("/artifact-content/lib/"),
      );
      await visitor.goto(new URL(publicUrl!).pathname);

      const body = await (await content).text();
      expect(body, "the public page's document carries a record").not.toContain(LIVE_RECORD_TITLE);
      const frame = framedPage(visitor, fixture.title);
      await expect(frame.locator("#marker")).toHaveText("v2");
      await expect(frame.locator("#state")).toHaveText("unavailable", { timeout: 15_000 });
      await expect(frame.locator("#rows")).toBeEmpty();
      expect(reads, "the public page asked for live data").toEqual([]);
    } finally {
      await stranger.close();
    }
  });

  test("the list shows Live and the thumbnail gets no data", async ({ page }) => {
    await watch(page);
    const reads: string[] = [];
    page.on("request", (request) => {
      if (DATA_PATH.test(new URL(request.url()).pathname)) reads.push(request.url());
    });
    await page.goto("/artifacts");
    // Searched to this one artifact, so the canary check reads only its thumbnail.
    await page.getByPlaceholder("Search artifacts…").fill(fixture.title);

    // The card's link covers it and holds no text, so the card is the link's parent.
    const card = page.locator(`a[href$="/artifacts/${fixture.artifactId}"]`).locator("..");
    await expect(card).toContainText(fixture.title);
    await expect(card.getByText("Live", { exact: true })).toBeVisible();
    const thumbnail = card.locator(`iframe[title="${fixture.title}"]`).contentFrame();
    await expect(thumbnail.locator("#marker")).toHaveText("v2");
    await expect(thumbnail.locator("#state")).toHaveText("unavailable");
    await expect(thumbnail.locator("#rows")).toBeEmpty();
    expect(reads, "the list read a page's live data").toEqual([]);
  });
});
