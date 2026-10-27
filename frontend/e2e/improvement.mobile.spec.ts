import type { APIRequestContext, Page, TestInfo } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE, walkPageTour } from "./helpers";

test.use({ storageState: AUTH_STATE });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Expected an API object");
  return value;
}
function id(value: Record<string, unknown>): string {
  if (typeof value.id !== "string") throw new Error("Expected a persisted resource identity");
  return value.id;
}
function items(value: Record<string, unknown>): Record<string, unknown>[] {
  if (!Array.isArray(value.items)) throw new Error("Expected an API collection");
  return value.items.map(record);
}
async function read(api: APIRequestContext, path: string, headers: Record<string, string>) {
  const response = await api.get(`/api${path}`, { headers });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return record(await response.json());
}
async function write(
  api: APIRequestContext,
  method: "post" | "put" | "patch",
  path: string,
  headers: Record<string, string>,
  data: object,
) {
  const response = await api[method](`/api${path}`, { headers, data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return record(await response.json());
}

/** An agent answering from the stub with a question set it fails, measured once, and an improver.
 * Unique resources keep each phone journey independent of other writers.
 */
async function seedImprovableAgent(page: Page) {
  await page.goto("/agents");
  const activeOrganization = () =>
    page.evaluate(() => {
      const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
      if (typeof value !== "object" || value === null || !("state" in value)) return null;
      const state = value.state;
      return typeof state === "object" &&
        state !== null &&
        "activeOrgId" in state &&
        typeof state.activeOrgId === "string"
        ? state.activeOrgId
        : null;
    });
  await expect.poll(activeOrganization).toBeTruthy();
  const organizationId = await activeOrganization();
  const headers = { "X-Organization-Id": organizationId ?? "" };
  const api = page.request;
  const stamp = Date.now().toString(36);
  await write(api, "patch", `/orgs/${organizationId}`, headers, { ai_assistance_enabled: true });
  const secret = await write(api, "post", "/secrets", headers, {
    name: `improvement-${stamp}`,
    purpose: "openai",
    value: { kind: "api_key", api_key: "sk-e2e-stub-not-a-real-key" },
  });
  const model = await write(api, "post", "/providers/model-profiles", headers, {
    label: `Improvement model ${stamp}`,
    provider: "openai",
    model: "gpt-4.1-mini",
    secret_id: id(secret),
    base_url: `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`,
    api: "chat",
  });
  const agent = await write(api, "post", "/agents", headers, {
    spec: {
      name: `E2E-IMPROVEMENT ${stamp}`,
      instructions: "E2E-IMPROVEMENT. Reply with exactly PONG-IMPROVEMENT-BEFORE and nothing else.",
      model_profile_id: id(model),
    },
  });
  await write(api, "post", `/agents/${id(agent)}/publish`, headers, {});
  const helper = await write(api, "post", "/agents/system", headers, {
    kind: "improver",
    name: `E2E Improver ${stamp}`,
    model_profile_id: id(model),
  });
  expect(helper.current_version_id).toBeTruthy();
  const dataset = await write(api, "post", "/datasets", headers, {
    name: `Return policy ${stamp}`,
  });
  await write(api, "put", `/datasets/${id(dataset)}/scoring`, headers, {
    checks: { enabled: true, required: true },
    trajectory: { enabled: false },
    judge: { enabled: false },
    reference: { enabled: false },
    review: { select: "all" },
  });
  let train = 0,
    holdout = 0;
  for (let n = 0; n < 40 && (train < 3 || holdout < 5); n++) {
    const question = await write(api, "post", `/datasets/${id(dataset)}/cases`, headers, {
      input: `Return policy question ${n + 1}`,
      checks: [{ type: "equals", value: "PONG-IMPROVEMENT-AFTER" }],
    });
    if (question.improvement_partition === "train") train++;
    else holdout++;
  }
  expect(train).toBeGreaterThanOrEqual(3);
  expect(holdout).toBeGreaterThanOrEqual(5);
  const initial = await write(api, "post", `/agents/${id(agent)}/eval-runs`, headers, {
    dataset_id: id(dataset),
    reruns: 0,
  });
  await expect
    .poll(async () => (await read(api, `/eval-runs/${id(initial)}`, headers)).status, {
      timeout: 90_000,
    })
    .toBe("completed");
  return { api, headers, stamp, model, agent, helper, dataset, initial };
}

/** Actual API, worker and persisted rows; only the external model is a fixture. */
test("test questions, review and improvement publish keep a guarded environment on its version", async ({
  page,
}, info) => {
  test.setTimeout(420_000);
  const { api, headers, stamp, model, agent, helper, dataset, initial } =
    await seedImprovableAgent(page);
  await page.goto("/datasets");
  await expect(page.getByText(String(dataset.name), { exact: true })).toBeVisible();
  await capture(page, info, "datasets");
  await page.goto(`/agents/${id(agent)}?tab=evals`);
  await expect(page.getByText(String(dataset.name), { exact: false }).first()).toBeVisible();
  const measuredRow = page.locator(`a[href="/agents/${id(agent)}/evals/${id(initial)}"]`).first();
  await expect(measuredRow).toBeVisible();
  const clipped = await measuredRow.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const outside: string[] = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const range = document.createRange();
      range.selectNodeContents(node);
      if (
        [...range.getClientRects()].some(
          (rect) =>
            rect.width > 0 && (rect.right > bounds.right + 1 || rect.left < bounds.left - 1),
        )
      )
        outside.push(node.textContent ?? "");
    }
    return outside;
  });
  expect(clipped, "model labels and prices must fit inside the phone's run card").toEqual([]);
  await capture(page, info, "agent-evals");
  const judge = await write(api, "post", "/agents/system", headers, {
    kind: "judge",
    name: `Policy grader ${stamp}`,
    model_profile_id: id(model),
  });
  await page.goto(`/agents/${id(judge)}`);
  await expect(page.getByRole("heading", { name: String(judge.name), exact: false })).toBeVisible();
  await capture(page, info, "judge");
  await page.goto(`/datasets/${id(dataset)}`);
  await expect(
    page.getByRole("heading", { name: String(dataset.name), exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Return policy question 1", { exact: true })).toBeVisible();
  await capture(page, info, "dataset-cases");
  await page.getByRole("button", { name: /^Return policy question 1\b/ }).click();
  const editor = page.getByRole("dialog");
  const editCase = editor.getByRole("button", { name: "Edit", exact: true });
  await expect(editCase).toBeVisible();
  await editCase.click();
  await expect(editor.getByRole("textbox", { name: "Input", exact: true })).toHaveValue(
    "Return policy question 1",
  );
  expect(
    await editor
      .getByRole("textbox", { name: "Input", exact: true })
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
  ).toBeGreaterThanOrEqual(16);
  await capture(page, info, "case-editor");
  await editor.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("tab", { name: /Generated/ }).click();
  await capture(page, info, "dataset-generated");
  await page.getByRole("tab", { name: "Grading", exact: true }).click();
  await capture(page, info, "dataset-grading");
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  // An eval run queues nothing for review by itself, so its answers are under all results.
  await page.getByRole("button", { name: /^All results \(\d+\)$/ }).click();
  await expect(page.getByText("Return policy question 1", { exact: true })).toBeVisible();
  await capture(page, info, "dataset-review");
  await page.getByText("Return policy question 1", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "Note", exact: true })
    .fill("Confirmed the reviewed policy expectation.");
  const reviewedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      /\/scores\/[^/]+\/verdict$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: "Answer is wrong", exact: true }).click();
  const reviewed = await reviewedResponse;
  expect(reviewed.ok()).toBeTruthy();
  const storedReview = record(await reviewed.json());
  expect(storedReview.human_passed).toBe(false);
  expect(storedReview.human_note).toBe("Confirmed the reviewed policy expectation.");
  await page.goto(`/agents/${id(agent)}/evals/${id(initial)}`);
  await expect(page.getByText("Return policy question 1", { exact: true })).toBeVisible();
  await capture(page, info, "eval-run");

  // A guard with no passing result must hold the current environment still.
  const environments = items(await read(api, `/agents/${id(agent)}/environments`, headers));
  const environment = environments.find((item) => item.is_default === true);
  expect(environment).toBeDefined();
  if (!environment) throw new Error("First publish did not create its environment");
  const originalVersion = environment.version_id;
  const guardDataset = await write(api, "post", "/datasets", headers, {
    name: `Production guard ${stamp}`,
  });
  await write(api, "put", `/datasets/${id(guardDataset)}/scoring`, headers, {
    checks: { enabled: true, required: true },
    trajectory: { enabled: false },
    judge: { enabled: false },
    reference: { enabled: false },
  });
  await write(api, "post", `/datasets/${id(guardDataset)}/cases`, headers, {
    input: "Guarded production policy",
    checks: [{ type: "equals", value: "A separate production policy still needs review" }],
  });
  const suite = await write(api, "post", `/agents/${id(agent)}/eval-suites`, headers, {
    name: `Policy guard ${stamp}`,
    dataset_id: id(guardDataset),
    threshold: { min_pass_rate: 1 },
    max_run_usd: "5",
    on_publish: false,
  });
  await write(api, "patch", `/agents/${id(agent)}/environments/${id(environment)}`, headers, {
    tracks_latest: true,
    guard_suite_ids: [id(suite)],
  });

  await page.goto(`/agents/${id(agent)}/improve/new`);
  await page.getByText("Show details", { exact: true }).click();
  await page.getByLabel("Test questions", { exact: true }).click();
  await page.getByRole("option", { name: String(dataset.name), exact: true }).click();
  const estimate = page.getByText(/^About \d+ minutes?, up to .+ \(estimate\)/);
  // The estimate redraws the box above the helper; a list opened before it lands
  // stays where it was drawn, off a phone's screen.
  await expect(estimate).toBeVisible();
  await page.getByText("Helper that writes the changes", { exact: true }).click();
  const runWith = page.getByRole("combobox", { name: "Run with" });
  await runWith.scrollIntoViewIfNeeded();
  await runWith.click();
  await page.getByRole("option", { name: String(helper.name), exact: true }).click();
  await expect(estimate).toBeVisible();
  const budget = page.getByLabel("Session spending limit (USD)");
  await expect(budget).toBeVisible();
  expect(
    await budget.evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
  ).toBeGreaterThanOrEqual(16);
  await budget.fill("5");
  await capture(page, info, "improvement-start");
  await page.getByRole("button", { name: "Start improving" }).click();
  await expect(page).toHaveURL(/\/improve\/[0-9a-f-]+$/);
  const sessionId = new URL(page.url()).pathname.split("/").at(-1);
  await expect
    .poll(
      async () =>
        (await read(api, `/agents/${id(agent)}/improvements/${sessionId}`, headers)).status,
      { timeout: 180_000 },
    )
    .toBe("ready");
  await page.reload();
  await expect(page.getByText(/Better: fixes \d+, breaks nothing/)).toBeVisible();
  await capture(page, info, "improvement-result");
  await page.getByRole("button", { name: "Changes", exact: true }).click();
  await expect(page.getByText("PONG-IMPROVEMENT-AFTER", { exact: false }).first()).toBeVisible();
  await capture(page, info, "improvement-changes");
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByRole("button", { name: "Publish version 2" })).toBeDisabled();
  await capture(page, info, "improvement-accept");
  await page.getByLabel("I have reviewed the selected changes and want to apply them.").check();
  await page.getByRole("button", { name: "Publish version 2" }).click();
  await expect(page.getByRole("link", { name: "Open version 2" })).toBeVisible();
  const published = await read(api, `/agents/${id(agent)}/improvements/${sessionId}`, headers);
  expect(published.status).toBe("published");
  expect(published.published_version).toBe(2);
  await expect
    .poll(
      async () =>
        items(await read(api, `/agents/${id(agent)}/eval-suites/${id(suite)}/results`, headers))[0]
          ?.status,
      { timeout: 90_000 },
    )
    .toBe("failed");
  const after = items(await read(api, `/agents/${id(agent)}/environments`, headers)).find(
    (item) => id(item) === id(environment),
  );
  expect(after?.version_id).toBe(originalVersion);
  expect(published.published_version_id).not.toBe(originalVersion);
  await page.reload();
  await page.getByRole("link", { name: "Open version 2" }).click();
  await expect(page.getByRole("textbox", { name: "Published specification" })).toHaveValue(
    /PONG-IMPROVEMENT-AFTER/,
  );
  await capture(page, info, "published-version");
});

test("a first improvement offers the automatic check, and ticking it creates the suite", async ({
  page,
}) => {
  test.setTimeout(420_000);
  const { api, headers, agent, helper, dataset } = await seedImprovableAgent(page);
  expect(items(await read(api, `/agents/${id(agent)}/eval-suites`, headers))).toEqual([]);
  const session = await write(api, "post", `/agents/${id(agent)}/improvements`, headers, {
    dataset_id: id(dataset),
    improver_agent_id: id(helper),
    max_iterations: 3,
    budget_usd: "5",
  });
  await expect
    .poll(
      async () =>
        (await read(api, `/agents/${id(agent)}/improvements/${id(session)}`, headers)).status,
      { timeout: 180_000 },
    )
    .toBe("ready");
  await page.goto(`/agents/${id(agent)}/improve/${id(session)}`);
  const wizard = page.url();
  const stops = await walkPageTour(page);
  expect(stops[0]).toBe("Test questions");
  expect(stops).toEqual(expect.arrayContaining(["Today", "Result"]));
  expect(page.url()).toBe(wizard);
  await expect(page.getByText("Something went wrong")).toHaveCount(0);
  // The walk leaves the wizard on its last stop, under the guided run it offers.
  await page.goto(wizard);
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByLabel(/^Check these questions automatically/)).toBeChecked();
  await page.getByLabel("I have reviewed the selected changes and want to apply them.").check();
  await page.getByRole("button", { name: "Publish version 2" }).click();
  await expect(page.getByRole("link", { name: "Open version 2" })).toBeVisible();
  const suites = items(await read(api, `/agents/${id(agent)}/eval-suites`, headers));
  expect(suites).toHaveLength(1);
  const [suite] = suites;
  expect(suite).toMatchObject({ dataset_id: id(dataset), on_publish: true });
  expect(record(suite?.threshold).max_confirmed_regressions).toBe(0);
});

test("a session kept as a draft is history: Improve starts the next, and the history reads it", async ({
  page,
}) => {
  test.setTimeout(420_000);
  const { api, headers, agent, helper, dataset } = await seedImprovableAgent(page);
  const session = await write(api, "post", `/agents/${id(agent)}/improvements`, headers, {
    dataset_id: id(dataset),
    improver_agent_id: id(helper),
    max_iterations: 3,
    budget_usd: "5",
  });
  await expect
    .poll(
      async () =>
        (await read(api, `/agents/${id(agent)}/improvements/${id(session)}`, headers)).status,
      { timeout: 180_000 },
    )
    .toBe("ready");
  await page.goto(`/agents/${id(agent)}/improve/${id(session)}`);
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await page.getByLabel("I have reviewed the selected changes and want to apply them.").check();
  await page.getByRole("button", { name: "Keep as draft" }).click();
  const decided = page.getByRole("region", { name: "What was decided" });
  await expect(decided).toContainText("Kept as a draft");

  // Every Improve entry lands here; with nothing open it stays on a new session.
  await page.goto(`/agents/${id(agent)}/improve/new?resume=1`);
  await expect(page.getByRole("button", { name: "Start improving" })).toBeVisible();
  await expect(page).toHaveURL(/\/improve\/new\?resume=1$/);

  await page.goto(`/agents/${id(agent)}?tab=history`);
  await page.getByRole("link", { name: /Kept as draft/ }).click();
  await expect(page).toHaveURL(new RegExp(`/improve/${id(session)}$`));
  await expect(page.getByText(/This improvement is finished/)).toBeVisible();
  await expect(decided).toContainText("Kept as a draft");
  await expect(page.getByRole("button", { name: "Keep as draft" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Publish version/ })).toHaveCount(0);
});

async function capture(page: Page, info: TestInfo, name: string) {
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.classList.toggle("dark", value === "dark");
    }, theme);
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
        `${name} ${theme} ${width}: horizontal overflow`,
      ).toBeLessThanOrEqual(0);
      await page.screenshot({
        path: info.outputPath(`${name}-${theme}-${width}.png`),
        fullPage: true,
        animations: "disabled",
      });
    }
  }
  await page.setViewportSize({ width: 390, height: 1000 });
}
