import type {
  APIRequestContext,
  APIResponse,
  BrowserContext,
  FrameLocator,
  Page,
} from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  COLLEAGUE_PASSWORD,
  FAKE_KEY_LABEL,
  STUB_MODEL_ENDPOINT,
  json,
  nowMatching,
  rowsAt,
  signInAs,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * A page that starts a workflow, from the run that publishes it to the answer it
 * draws.
 *
 * Nothing here is set up by writing an artifact row. A workflow with a Manual
 * trigger and one declared field is created and published through the API; an
 * agent that binds it publishes the page through a real run, the stub model
 * calling `publish_artifact` with `actions` naming the workflow
 * (`CALL-TOOL` in `stub-model-server.ts`).
 *
 * **What is asserted is inside the page**: `#result` is what the page's own
 * `agenticos.run` promise settled with. The strip around the page renders the
 * same whether or not a run ever started, so it is only used for what it alone
 * shows - the "This page can run" menu and the confirmation dialog.
 *
 * The workflow is private and the colleague is a Member, who runs only what is
 * shared with them. So the journey is the refusal first - no menu, and the page's
 * call is rejected at once - then the owner shares the workflow, then the
 * colleague declines once (and nothing starts) and confirms once (and the page
 * gets the workflow's answer, a run recorded as started by an app).
 *
 * The run's end needs the workflow worker (`make dev` starts it; CI's e2e job has
 * none, so it sets no `E2E_WORKER=1`). Without it the journey still proves the run
 * was admitted - the page's progress shows it queued or running and an app run
 * exists - and the answer is asserted only with the worker.
 */

/** Long enough for the runs and the polls behind them, on a dev server that compiles. */
const SETUP_TIMEOUT = 180_000;

/** How long a started workflow may take to answer: a worker picks it up through the job queue. */
const RUN_TIMEOUT = 90_000;

/** What the page calls its button's action - never the workflow's own name. */
const ACTION_LABEL = "Send note";

/** The page's own words for a call the console refused before it asked anyone. */
const CANNOT_ACT = /^rejected:unavailable$/;

/** Statuses of a run that has not ended; the rest are terminal. */
const LIVE = ["queued", "running", "waiting_approval", "waiting_retry", "needs_attention"];

/** The workflow worker is running (`make dev` starts one; CI's e2e job has none). */
const WORKER = process.env.E2E_WORKER === "1";

/** The page. It runs `agenticos.run` only on a click, never on load. */
function pageHtml(note: string): string {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Note sender</title></head>
<body>
<p id="marker">actions-v1</p>
<input id="note" value="${note}">
<button id="go" type="button">Send</button>
<p>Result <span id="result">idle</span></p>
<p>Progress <span id="progress">none</span></p>
<script>
var out = document.getElementById("result");
var progress = document.getElementById("progress");
agenticos.onRun(function (p) { progress.textContent = p.status; });
document.getElementById("go").addEventListener("click", function () {
  out.textContent = "asking";
  agenticos.run(${JSON.stringify(ACTION_LABEL)}, { note: document.getElementById("note").value }).then(
    function (run) { out.textContent = "done:" + run.status + ":" + run.output_text; },
    function (error) { out.textContent = "rejected:" + error.message; }
  );
});
</script>
</body></html>`;
}

/** The prompt that makes the stub call `publish_artifact` with exactly these arguments. */
function publishPrompt(args: Record<string, unknown>): string {
  const encoded = Buffer.from(JSON.stringify(args), "utf8").toString("base64url");
  return `Publish the page. CALL-TOOL:publish_artifact:${encoded}`;
}

/** The framed page in the viewer, by the title the frame carries. */
function framedPage(page: Page, title: string): FrameLocator {
  return page.locator(`iframe[title="${title}"]`).first().contentFrame();
}

/**
 * A Manual-trigger workflow that answers with the `note` it was started with:
 * trigger -> output, the output's text bound to the trigger's payload field.
 */
function echoGraph(): Record<string, unknown> {
  const trigger = crypto.randomUUID();
  const output = crypto.randomUUID();
  const layout = { x: 0, y: 0 };
  return {
    entry_node_id: trigger,
    nodes: [
      {
        id: trigger,
        definition_id: "trigger.manual",
        definition_version: 1,
        config: { fields: [{ name: "note", label: "Note", type: "text", required: true }] },
        layout,
      },
      { id: output, definition_id: "core.output", definition_version: 1, config: {}, layout },
    ],
    edges: [
      {
        id: crypto.randomUUID(),
        source_node_id: trigger,
        source_port: "out",
        target_node_id: output,
        target_port: "in",
      },
    ],
    bindings: [
      {
        target_node_id: output,
        target_field: "text",
        source: {
          kind: "node_output",
          node_id: trigger,
          port: "out",
          field_path: ["payload", "note"],
        },
      },
    ],
  };
}

/** A 2xx, or a failure that says what the API answered. */
async function ok(response: APIResponse, what: string): Promise<void> {
  if (!response.ok()) {
    expect(response.ok(), `${what} answered ${response.status()}: ${await response.text()}`).toBe(
      true,
    );
  }
}

/** Everything the spec made, by id, for the tests and for the teardown. */
interface Fixture {
  stamp: string;
  title: string;
  note: string;
  workflowName: string;
  workflowId: string;
  artifactId: string;
  agentId: string;
  profileId: string;
  colleagueId: string;
}

let fixture: Fixture;
let owner: BrowserContext | undefined;
let colleagueContext: BrowserContext | undefined;

async function ownerRequest(
  browser: import("@playwright/test").Browser,
): Promise<APIRequestContext> {
  owner ??= await browser.newContext({ storageState: AUTH_STATE });
  return owner.request;
}

async function asColleague(browser: import("@playwright/test").Browser): Promise<BrowserContext> {
  colleagueContext ??= await signInAs(browser, COLLEAGUE_EMAIL, COLLEAGUE_PASSWORD);
  return colleagueContext;
}

/** The runs an app started of the spec's workflow. */
async function appRuns(request: APIRequestContext): Promise<Record<string, unknown>[]> {
  return rowsAt(request, `/api/workflow-runs?workflow_id=${fixture.workflowId}&triggered_by=app`);
}

test.describe("artifact actions", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(SETUP_TIMEOUT);
    const request = await ownerRequest(browser);
    const stamp = Date.now().toString(36);
    const title = `E2E Actions ${stamp}`;
    fixture = {
      stamp,
      title,
      note: `e2e-note-${stamp}`,
      workflowName: `E2E Echo ${stamp}`,
      workflowId: "",
      artifactId: "",
      agentId: "",
      profileId: "",
      colleagueId: "",
    };

    const orgs = await json<{ items: { id: string }[] }>(request, "/api/orgs");
    const colleague = (await rowsAt(request, `/api/orgs/${orgs.items[0]!.id}/members`)).find(
      (row) => row.email === COLLEAGUE_EMAIL,
    );
    expect(colleague, "the colleague is not a member; did the seed run?").toBeDefined();
    fixture.colleagueId = String(colleague!.user_id);

    // The workflow: private, so a Member holds no right to run it until it is shared.
    const created = await request.post("/api/workflows", {
      data: { name: fixture.workflowName, visibility: "private" },
    });
    await ok(created, "creating the workflow");
    fixture.workflowId = ((await created.json()) as { id: string }).id;
    const drafted = await request.patch(`/api/workflows/${fixture.workflowId}/draft`, {
      data: { graph: echoGraph(), expected_revision: 0 },
    });
    await ok(drafted, "writing the workflow's draft");
    const revision = ((await drafted.json()) as { draft_revision: number }).draft_revision;
    await ok(
      await request.post(`/api/workflows/${fixture.workflowId}/publish`, {
        data: { expected_revision: revision },
      }),
      "publishing the workflow",
    );

    // A model on the stub, keyed by the seed's provider key - the stub checks none.
    const key = (await rowsAt(request, "/api/secrets")).find((row) => row.name === FAKE_KEY_LABEL);
    expect(key, `no secret is named ${FAKE_KEY_LABEL}`).toBeDefined();
    const profile = await request.post("/api/providers/model-profiles", {
      data: {
        label: `e2e-actions-model-${stamp}`,
        provider: "openai",
        model: "gpt-4.1-mini",
        secret_id: key!.id,
        base_url: STUB_MODEL_ENDPOINT,
      },
    });
    await ok(profile, "creating the stub model profile");
    fixture.profileId = ((await profile.json()) as { id: string }).id;

    // The agent: Artifacts to publish, and the one workflow its page may name.
    const spec = {
      name: `E2E Actions Publisher ${stamp}`,
      instructions: "You are an E2E fixture. Do what the message says.",
      model_profile_id: fixture.profileId,
      capabilities: [
        { id: "artifacts" },
        { id: "workflows", config: { workflow_ids: [fixture.workflowId] } },
      ],
    };
    const agent = await request.post("/api/agents", { data: { spec: { name: spec.name } } });
    await ok(agent, "creating the agent");
    fixture.agentId = ((await agent.json()) as { id: string }).id;
    await ok(
      await request.put(`/api/agents/${fixture.agentId}/draft`, { data: { spec } }),
      "the agent's draft",
    );
    await ok(
      await request.post(`/api/agents/${fixture.agentId}/publish`, { data: {} }),
      "publishing",
    );

    // The signed-in owner is the person behind the run, which is what lets it
    // declare actions at all.
    const run = await request.post(`/api/agents/${fixture.agentId}/run`, {
      data: {
        prompt: publishPrompt({
          name: `e2e-actions-${stamp}`,
          title,
          content: pageHtml(fixture.note),
          actions: [{ workflow: fixture.workflowId, label: ACTION_LABEL }],
        }),
      },
      timeout: SETUP_TIMEOUT,
    });
    await ok(run, "the publishing run");
    const listed = await nowMatching(
      request,
      `/api/apps?q=${encodeURIComponent(title)}`,
      (row) => row.title === title,
      `an artifact titled ${title}`,
    );
    fixture.artifactId = String(listed.id);

    // The declaration took: the owner's own view lists the action, under the
    // workflow's real name and the field it asks for.
    const view = await json<{
      actions: { name: string; label: string; fields: { name: string }[] }[];
    }>(request, `/api/apps/${fixture.artifactId}/view?data=true`);
    expect(view.actions).toMatchObject([
      { name: fixture.workflowName, label: ACTION_LABEL, fields: [{ name: "note" }] },
    ]);

    // The colleague may open the page; the workflow is not shared yet.
    await ok(
      await request.put(`/api/apps/${fixture.artifactId}/sharing/grants`, {
        data: { subject_user_id: fixture.colleagueId, level: "read" },
      }),
      "sharing the page with the colleague",
    );
  });

  test.afterAll(async ({ browser }) => {
    const request = await ownerRequest(browser);
    try {
      if (fixture !== undefined) {
        // A workflow with a live run is in use (409 WORKFLOW_IN_USE): cancel those first.
        if (fixture.workflowId) {
          for (const row of await appRuns(request)) {
            if (LIVE.includes(String(row.status))) {
              await request.post(`/api/workflow-runs/${row.id}/cancel`);
            }
          }
        }
        // In dependency order: the page names the agent, the agent the workflow and
        // the profile. The workflow's runs go with it.
        const paths = [
          fixture.artifactId && `/api/apps/${fixture.artifactId}`,
          fixture.agentId && `/api/agents/${fixture.agentId}`,
          fixture.workflowId && `/api/workflows/${fixture.workflowId}`,
          fixture.profileId && `/api/providers/model-profiles/${fixture.profileId}`,
        ].filter(Boolean);
        const failed: string[] = [];
        for (const path of paths) {
          const removed = await request.delete(path as string);
          if (!removed.ok()) failed.push(`${path} answered ${removed.status()}`);
        }
        expect(failed, "teardown left these behind").toEqual([]);
      }
    } finally {
      await owner?.close();
      await colleagueContext?.close();
    }
  });

  test("a member who may not run the workflow is offered no action", async ({ browser }) => {
    const colleague = await (await asColleague(browser)).newPage();
    try {
      await colleague.goto(`/apps/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      // The page is drawn, so the view that lists actions has been answered.
      await expect(frame.locator("#marker")).toHaveText("actions-v1");
      await expect(colleague.getByRole("button", { name: /This page can run/ })).toHaveCount(0);

      await frame.locator("#go").click();
      await expect(frame.locator("#result")).toHaveText(CANNOT_ACT);
      await expect(colleague.getByRole("dialog")).toHaveCount(0);
    } finally {
      await colleague.close();
    }
    expect(await appRuns(await ownerRequest(browser)), "a run started anyway").toEqual([]);
  });

  test("a member who declines starts nothing", async ({ browser }) => {
    const request = await ownerRequest(browser);
    await ok(
      await request.put(`/api/workflows/${fixture.workflowId}/sharing/grants`, {
        data: { subject_user_id: fixture.colleagueId, level: "use" },
      }),
      "sharing the workflow with the colleague",
    );

    const colleague = await (await asColleague(browser)).newPage();
    try {
      await colleague.goto(`/apps/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      await expect(frame.locator("#marker")).toHaveText("actions-v1");
      // The workflow's own name, never the page's label.
      await expect(
        colleague.getByRole("button", { name: `This page can run: ${fixture.workflowName}` }),
      ).toBeVisible();
      // Nothing runs on load: the page asks only when its button is pressed.
      await expect(frame.locator("#result")).toHaveText("idle");

      await frame.locator("#go").click();
      const dialog = colleague.getByRole("dialog", { name: fixture.workflowName });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
      await expect(frame.locator("#result")).toHaveText("rejected:cancelled");
    } finally {
      await colleague.close();
    }
    expect(await appRuns(request), "declining started a run").toEqual([]);
  });

  test("a member who confirms gets the workflow's answer", async ({ browser }) => {
    test.setTimeout(RUN_TIMEOUT + 60_000);
    const colleague = await (await asColleague(browser)).newPage();
    try {
      await colleague.goto(`/apps/${fixture.artifactId}`);
      const frame = framedPage(colleague, fixture.title);
      await expect(frame.locator("#marker")).toHaveText("actions-v1");

      await frame.locator("#go").click();
      const dialog = colleague.getByRole("dialog", { name: fixture.workflowName });
      await expect(dialog).toBeVisible();
      // What the person is asked: the page's wording as a quote, and every value it sends.
      await expect(dialog).toContainText(ACTION_LABEL);
      await expect(dialog).toContainText("Note");
      await expect(dialog).toContainText(fixture.note);
      // Run waits a moment before it can be pressed.
      const run = dialog.getByRole("button", { name: "Run", exact: true });
      await expect(run).toBeEnabled();
      await run.click();
      await expect(dialog).toBeHidden();

      // The run was admitted: the page's own listener saw it start.
      await expect(frame.locator("#progress")).toHaveText(/^(queued|running|succeeded)$/, {
        timeout: RUN_TIMEOUT,
      });

      // The page gets the answer: the workflow echoed the input it was started with.
      if (WORKER) {
        await expect(
          frame.locator("#result"),
          "the run never finished; is the workflow worker running?",
        ).toHaveText(`done:succeeded:${fixture.note}`, { timeout: RUN_TIMEOUT });
      }
    } finally {
      await colleague.close();
    }

    // One run, the colleague's own, recorded as started by an app.
    const request = await ownerRequest(browser);
    const started = await nowMatching(
      request,
      `/api/workflow-runs?workflow_id=${fixture.workflowId}&triggered_by=app`,
      (row) => row.triggered_by === "app" && [...LIVE, "succeeded"].includes(String(row.status)),
      "an app run, queued or running or done",
    );
    if (WORKER) expect(started.status).toBe("succeeded");
    expect(await appRuns(request)).toHaveLength(1);
  });
});
