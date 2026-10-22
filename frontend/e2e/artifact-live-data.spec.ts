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
  submitDialog,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * A page bound to a page query, from the run that publishes it to the people
 * who may and may not read its records.
 *
 * Nothing here is set up by writing an artifact row: an agent publishes the
 * page through a real run, the stub model calling `publish_artifact` with the
 * page and its bindings this spec spelled out (`CALL-TOOL` in
 * `stub-model-server.ts`). A binding names the seeded shared view, whose filters
 * the capability copies into the page's own query, so what the console reads is
 * a query the capability resolved against the agent's own table grant.
 *
 * Everyone who opens the page reads that query with its **owner's** access, once
 * the owner has confirmed sharing it. The journey follows that consent: the owner
 * alone reads a new page's data; a colleague asks to open it and is let in only
 * after the owner confirms the data; the owner withdraws and confirms again; and
 * an editor's republish that reads more waits as a request the owner reviews.
 *
 * **What is asserted is inside the page**, because the strip around it renders
 * the same whether or not a record ever crossed: `#state` is what the page's
 * own `agenticos.onData` was handed, `#rows` the titles it drew, and `#load` a
 * random id the document picks once per load - unchanged after Refresh is the
 * proof the page was updated in place rather than loaded again.
 *
 * A public link adds two more decisions: an admin allows public live data for the
 * organization, and the owner confirms the data for the link. The journey then opens
 * the link as a stranger, switches the organization off and on, and replaces the key.
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
  /** The page's name, which an editor's republish must repeat to update the same page. */
  pageName: string;
  /** The saved view the page's binding copies, and the colleague's grants to undo. */
  viewId: string;
  grantedTable: boolean;
  grantedAgent: boolean;
}

let fixture: Fixture;
let owner: BrowserContext | undefined;

/**
 * The organization's switch for public live data as this spec found it, kept once
 * the journey touches it so the teardown can put it back. `undefined` until then.
 */
let publicSwitch: { orgId: string; wasOn: boolean } | undefined;

async function ownerRequest(browser: Browser): Promise<APIRequestContext> {
  owner ??= await browser.newContext({ storageState: AUTH_STATE });
  return owner.request;
}

let colleagueContext: BrowserContext | undefined;

/** The colleague's own signed-in context, made once and closed at the teardown. */
async function asColleague(browser: Browser): Promise<BrowserContext> {
  colleagueContext ??= await signInAs(browser, COLLEAGUE_EMAIL, COLLEAGUE_PASSWORD);
  return colleagueContext;
}

/**
 * A 2xx, or a failure that says what the API answered. `status` pins the exact code:
 * a 202 is a grant held back for confirmation, which is a 2xx and not what a caller
 * that needed the grant applied asked for.
 */
async function ok(response: APIResponse, what: string, status?: number): Promise<void> {
  const accepted = status === undefined ? response.ok() : response.status() === status;
  if (!accepted) {
    expect(
      accepted,
      `${what} answered ${response.status()}${status === undefined ? "" : ` instead of ${status}`}: ${await response.text()}`,
    ).toBe(true);
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

/** Switch the organization's public live data on or off, and wait until it reads back. */
async function setPublicSwitch(
  request: APIRequestContext,
  orgId: string,
  allowed: boolean,
): Promise<void> {
  await ok(
    await request.patch(`/api/orgs/${orgId}`, { data: { public_live_data: allowed } }),
    `switching public live data ${allowed ? "on" : "off"}`,
  );
  await expect
    .poll(
      async () =>
        (await rowsAt(request, "/api/orgs")).find((row) => row.id === orgId)?.public_live_data,
      { message: `the organization never read back public_live_data=${allowed}` },
    )
    .toBe(allowed);
}

interface PublicDataDisclosure {
  confirmable: boolean;
  member_consent: boolean;
  fingerprint: string | null;
  audience_digest: string;
  problem?: string | null;
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
      pageName: `e2e-live-${stamp}`,
      viewId: String(view!.id),
      grantedTable: false,
      grantedAgent: false,
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
    const name = fixture.pageName;
    for (const marker of ["v1", "v2"]) {
      const run = await request.post(`/api/agents/${agentId}/run`, {
        data: {
          prompt: publishPrompt({
            name,
            title,
            content: pageHtml(marker),
            bindings: {
              [BINDING]: { view: view!.id, fields: { title: "Title" } },
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
    try {
      if (fixture !== undefined) {
        await retitle(request, LIVE_RECORD_TITLE);
        // What the editor journey lent the colleague, taken back: the table and the
        // agent outlive this spec, the page does not.
        const lent = [
          fixture.grantedTable &&
            `/api/tables/${fixture.tableId}/sharing/grants/${fixture.colleagueId}`,
          fixture.grantedAgent &&
            `/api/agents/${fixture.agentId}/sharing/grants/${fixture.colleagueId}`,
        ].filter((path): path is string => typeof path === "string");
        for (const path of lent) {
          const revoked = await request.delete(path);
          expect(revoked.ok(), `${path} answered ${revoked.status()} at teardown`).toBe(true);
        }
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
    } finally {
      // The organization's switch goes back to what it was, even when a delete above
      // failed; the link goes with the page.
      if (publicSwitch !== undefined) {
        await setPublicSwitch(request, publicSwitch.orgId, publicSwitch.wasOn);
      }
    }
    await owner?.close();
    await colleagueContext?.close();
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
    // The owner reads the data at once; nobody else does until they confirm it.
    await expect(
      page.getByText("Nobody has confirmed sharing the data v2 reads yet."),
    ).toBeVisible();
    await expect(
      page.getByRole("status").getByRole("button", { name: "Confirm data" }),
    ).toBeVisible();
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

    // The tests after this one read the seeded title, so it goes back here, not only
    // at the teardown.
    await retitle(page.request, LIVE_RECORD_TITLE);
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

  test("a member without access can ask the owner to open the page", async ({ browser }) => {
    const colleague = await (await asColleague(browser)).newPage();
    try {
      await colleague.goto(`/artifacts/${fixture.artifactId}`);

      // Nothing of the page is told: not its title, its owner or its agent.
      await expect(colleague.getByText("You don't have access to this page")).toBeVisible();
      await expect(colleague.getByText(fixture.title)).toHaveCount(0);
      await colleague.getByLabel("Note for the owner (optional)").fill("For the Monday review");
      await colleague.getByRole("button", { name: "Request access" }).click();
      await expect(colleague.getByText("Access requested")).toBeVisible();
    } finally {
      await colleague.close();
    }

    const ownerApi = await ownerRequest(browser);
    const asked = await nowMatching(
      ownerApi,
      `/api/artifacts/${fixture.artifactId}/share-requests`,
      (row) => row.kind === "access" && row.note === "For the Monday review",
      "a pending request for access with the colleague's note",
    );
    expect(asked.requester_user_id).toBe(fixture.colleagueId);
  });

  test("a request cannot be approved until the owner confirms the data", async ({ page }) => {
    const pending = await json<{ items: { id: string; kind: string }[] }>(
      page.request,
      `/api/artifacts/${fixture.artifactId}/share-requests`,
    );
    const request = pending.items.find((item) => item.kind === "access")!;
    const refused = await page.request.post(
      `/api/artifacts/${fixture.artifactId}/share-requests/${request.id}/approve`,
    );
    expect(refused.status(), "approving opened a page whose data nobody confirmed").toBe(409);
    expect(((await refused.json()) as { error?: { code?: string } }).error?.code).toBe(
      "CONSENT_REQUIRED",
    );

    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);
    await page.getByRole("status").getByRole("button", { name: "Confirm data" }).click();
    const dialog = page.getByRole("dialog", { name: /Confirm the data v2 shares/ });
    // The words come from the query the capability resolved, not from the page.
    await expect(dialog).toContainText(LIVE_TABLE_NAME);
    await expect(dialog).toContainText("Title (Text)");
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Confirm data" }),
      path: `/api/artifacts/${fixture.artifactId}/versions/`,
    });
    await expect(
      page.getByText("Data confirmed. Everyone who can open the page now reads it."),
    ).toBeVisible();
    await expect(page.getByText("Nobody has confirmed sharing the data")).toHaveCount(0);

    const detail = await json<{ consent: { state: string; shared: boolean } }>(
      page.request,
      `/api/artifacts/${fixture.artifactId}`,
    );
    expect(detail.consent).toMatchObject({ state: "consented", shared: true });
  });

  test("the owner approves the request and the member reads the records", async ({
    page,
    browser,
  }) => {
    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);
    await page.getByRole("button", { name: /request.* waiting for you/ }).click();
    const share = page.getByRole("dialog");
    await expect(share.getByText("Requests", { exact: true })).toBeVisible();
    await expect(share.getByText("For the Monday review")).toBeVisible();
    await share.getByRole("button", { name: /^Approve the request from/ }).click();
    await expect(page.getByText("Request approved")).toBeVisible();

    const colleague = await (await asColleague(browser)).newPage();
    try {
      await watch(colleague);
      await colleague.goto(`/artifacts/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      // Read with the owner's access: the colleague holds no grant on the table.
      await expect(frame.locator("#state")).toHaveText("ok");
      await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);
      await expect(frame.locator("#rows")).not.toContainText(LIVE_CLOSED_RECORD_TITLE);
    } finally {
      await colleague.close();
    }
  });

  test("withdrawing the data leaves the audience the page without it until it is confirmed again", async ({
    page,
    browser,
  }) => {
    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);
    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("menuitem", { name: "Stop sharing data" }).click();
    const stop = page.locator('[role="dialog"], [role="alertdialog"]');
    await submitDialog(page, {
      dialog: stop,
      submit: stop.getByRole("button", { name: "Stop sharing data" }),
      path: `/api/artifacts/${fixture.artifactId}/consent`,
      method: "DELETE",
    });
    await expect(
      page.getByText("Sharing stopped. Everyone keeps the page, without its data."),
    ).toBeVisible();

    const colleague = await (await asColleague(browser)).newPage();
    try {
      await watch(colleague);
      await colleague.goto(`/artifacts/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      await expect(frame.locator("#marker")).toHaveText("v2");
      await expect(frame.locator("#state")).toHaveText("unavailable");
      await expect(frame.locator("#rows")).toBeEmpty();
      await expect(
        colleague.getByText("This page's data appears once its owner confirms sharing it."),
      ).toBeVisible();
    } finally {
      await colleague.close();
    }

    // The same query, so the confirmation is the one the owner was shown before.
    await page.getByRole("status").getByRole("button", { name: "Confirm data" }).click();
    const reconfirm = page.getByRole("dialog", { name: /Confirm the data v2 shares/ });
    await submitDialog(page, {
      dialog: reconfirm,
      submit: reconfirm.getByRole("button", { name: "Confirm data" }),
      path: `/api/artifacts/${fixture.artifactId}/versions/`,
    });
    await expect(
      page.getByText("Data confirmed. Everyone who can open the page now reads it."),
    ).toBeVisible();

    const again = await (await asColleague(browser)).newPage();
    try {
      await watch(again);
      await again.goto(`/artifacts/${fixture.artifactId}`);
      const frame = framedPage(again, fixture.title);
      await expect(frame.locator("#state")).toHaveText("ok");
      await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);
    } finally {
      await again.close();
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

  test("a public link shows the data only while the switch and the owner's consent hold", async ({
    page,
    browser,
  }) => {
    const request = page.request;

    // An admin allows it for the organization: off until somebody does.
    const org = (await rowsAt(request, "/api/orgs"))[0]!;
    const orgId = String(org.id);
    publicSwitch = { orgId, wasOn: org.public_live_data === true };
    await setPublicSwitch(request, orgId, true);

    // The owner turns the link on and confirms the data for it, after the disclosure.
    const linked = await request.put(`/api/artifacts/${fixture.artifactId}/public-link`);
    await ok(linked, "turning the public link on");
    const publicUrl = ((await linked.json()) as { public_url: string | null }).public_url;
    expect(publicUrl, "the public link answered without an address").toBeTruthy();
    const path = new URL(publicUrl!).pathname;

    let disclosure!: PublicDataDisclosure;
    await expect
      .poll(
        async () => {
          disclosure = await json<PublicDataDisclosure>(
            request,
            `/api/artifacts/${fixture.artifactId}/public-data`,
          );
          return disclosure.confirmable;
        },
        { message: "the disclosure never became confirmable" },
      )
      .toBe(true);
    expect(disclosure.problem ?? null, "the disclosure refused confirming").toBeNull();
    expect(disclosure.member_consent, "the members' consent was missing").toBe(true);
    await ok(
      await request.post(`/api/artifacts/${fixture.artifactId}/public-data`, {
        data: {
          fingerprint: disclosure.fingerprint,
          audience_digest: disclosure.audience_digest,
          confirmed: true,
        },
      }),
      "confirming the data for the public link",
    );
    await expect
      .poll(
        async () =>
          (
            await json<{ public_data: { holds: boolean } | null }>(
              request,
              `/api/artifacts/${fixture.artifactId}`,
            )
          ).public_data?.holds,
        { message: "the public data consent never held" },
      )
      .toBe(true);

    // An anonymous browser reads the record, with no refresh and no data route.
    const stranger = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    try {
      const visitor = await stranger.newPage();
      await watch(visitor);
      const reads: string[] = [];
      visitor.on("request", (seen) => {
        if (/\/versions\/.+\/data/.test(new URL(seen.url()).pathname)) reads.push(seen.url());
      });
      await visitor.goto(path);
      const frame = framedPage(visitor, fixture.title);
      await expect(frame.locator("#state")).toHaveText("ok", { timeout: 15_000 });
      await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);
      await expect(frame.locator("#rows")).not.toContainText(LIVE_CLOSED_RECORD_TITLE);
      expect(reads, "the public page asked for live data itself").toEqual([]);

      // The switch off is a kill switch: the next load has the page and no data.
      await setPublicSwitch(request, orgId, false);
      await visitor.reload();
      await expect(frame.locator("#marker")).toHaveText("v2");
      await expect(frame.locator("#state")).toHaveText("unavailable", { timeout: 15_000 });
      await expect(frame.locator("#rows")).toBeEmpty();

      // Back on, the page's own consent still holds, so the data returns.
      await setPublicSwitch(request, orgId, true);
      await visitor.reload();
      await expect(frame.locator("#state")).toHaveText("ok", { timeout: 15_000 });
      await expect(frame.locator("#rows")).toContainText(LIVE_RECORD_TITLE);

      // Replacing the key is a new address; the old one is a 404, not a page without data.
      // The signed content address the open page was served from dies with the key too.
      const src = await visitor.locator("iframe").first().getAttribute("src");
      expect(src, "the framed page had no content address").toBeTruthy();
      const contentUrl = new URL(src!, visitor.url()).toString();
      const rotated = await request.put(`/api/artifacts/${fixture.artifactId}/public-link`);
      await ok(rotated, "rotating the public link");
      const newPath = new URL(((await rotated.json()) as { public_url: string }).public_url)
        .pathname;
      expect(newPath, "rotating the link kept its address").not.toBe(path);
      await expect
        .poll(async () => (await stranger.request.get(contentUrl)).status(), {
          message: "the old content address still served after the key was replaced",
        })
        .toBe(404);
      await expect
        .poll(async () => (await stranger.request.get(path)).status(), {
          message: "the replaced address still opened",
        })
        .toBe(404);
      const gone = await visitor.goto(path);
      expect(gone?.status(), "the replaced address still opened").toBe(404);
      await expect(visitor.locator("iframe")).toHaveCount(0);
      // The new address carries the data: rotating changes the URL, not the consent.
      await expect
        .poll(async () => (await stranger.request.get(newPath)).status(), {
          message: "the new address never served",
        })
        .toBe(200);
      await visitor.goto(newPath);
      await expect(frame.locator("#state")).toHaveText("ok", { timeout: 15_000 });
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

  test("an editor's republish that reads more waits for the owner's review", async ({
    page,
    browser,
  }) => {
    test.setTimeout(SETUP_TIMEOUT);
    // The colleague edits the page, runs the agent and reads the table: the
    // three things an editor's own publish needs, none of which is the owner's consent.
    const grants = [
      [`/api/artifacts/${fixture.artifactId}/sharing/grants`, "edit"],
      [`/api/agents/${fixture.agentId}/sharing/grants`, "use"],
      [`/api/tables/${fixture.tableId}/sharing/grants`, "read"],
    ] as const;
    for (const [path, level] of grants) {
      await ok(
        await page.request.put(path, {
          data: { subject_user_id: fixture.colleagueId, level },
        }),
        `granting ${level} at ${path}`,
        200,
      );
    }
    fixture.grantedAgent = true;
    fixture.grantedTable = true;

    const editor = await asColleague(browser);
    const run = await editor.request.post(`/api/agents/${fixture.agentId}/run`, {
      data: {
        prompt: publishPrompt({
          name: fixture.pageName,
          title: fixture.title,
          content: pageHtml("v3"),
          // One more column than v1 and v2 read.
          bindings: {
            [BINDING]: { view: fixture.viewId, fields: { title: "Title", status: "Status" } },
          },
        }),
      },
      timeout: SETUP_TIMEOUT,
    });
    await ok(run, "the editor's run");

    const waiting = await nowMatching(
      page.request,
      `/api/artifacts/${fixture.artifactId}/share-requests`,
      (row) => row.kind === "version" && row.version_number === 3,
      "a pending version request for v3",
    );
    expect(waiting.requester_user_id).toBe(fixture.colleagueId);
    // The audience keeps v2 while v3 waits.
    const before = await json<{ consent: { audience_version: number; state: string } }>(
      page.request,
      `/api/artifacts/${fixture.artifactId}`,
    );
    expect(before.consent).toMatchObject({ audience_version: 2, state: "pending" });

    await watch(page);
    await page.goto(`/artifacts/${fixture.artifactId}`);
    await expect(page.getByText(/changed what v3 reads/)).toBeVisible();
    await page.getByRole("button", { name: "Review data change" }).click();
    const review = page.getByRole("region", { name: "Review data change" });
    await expect(review).toContainText("Compared with v2");
    // The extra column is named, and marked as reading more.
    await expect(review).toContainText("Status");
    await expect(review).toContainText("Reads more");
    await review.getByRole("button", { name: "Approve" }).click();
    await expect(
      page.getByText("Data confirmed. Everyone who can open the page now reads it."),
    ).toBeVisible();

    await expect
      .poll(
        async () =>
          (
            await json<{ consent: { audience_version: number } }>(
              page.request,
              `/api/artifacts/${fixture.artifactId}`,
            )
          ).consent.audience_version,
        { message: "the audience was never moved to v3 after the owner approved it" },
      )
      .toBe(3);

    const colleague = await editor.newPage();
    try {
      await watch(colleague);
      await colleague.goto(`/artifacts/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      await expect(frame.locator("#marker")).toHaveText("v3");
      await expect(frame.locator("#state")).toHaveText("ok");
    } finally {
      await colleague.close();
    }
  });
});
