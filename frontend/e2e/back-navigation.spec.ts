import type { APIRequestContext, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

/**
 * Back returns to the view a page was opened from - the same tab, the same
 * list - by the browser's button and by the page's own arrow alike, and opening
 * one case or run over its page is a step Back closes. The file seeds its own
 * agent, dataset and run once, so it depends on no other writer.
 */
test.use({ storageState: AUTH_STATE });
test.describe.configure({ mode: "serial" });

type Row = Record<string, unknown>;

async function call(api: APIRequestContext, path: string, headers: Row, data: object) {
  const response = await api.post(`/api${path}`, {
    headers: headers as Record<string, string>,
    data,
  });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return (await response.json()) as Row;
}

/** An agent with one eval run on a dataset of one case. The run's outcome does not matter here. */
async function seed(page: Page) {
  await page.goto("/agents");
  const organization = () =>
    page.evaluate(() => {
      const stored = JSON.parse(localStorage.getItem("org-storage") ?? "null") as {
        state?: { activeOrgId?: string };
      } | null;
      return stored?.state?.activeOrgId ?? null;
    });
  await expect.poll(organization).toBeTruthy();
  const headers = { "X-Organization-Id": (await organization()) ?? "" };
  const api = page.request;
  const stamp = Date.now().toString(36);
  const secret = await call(api, "/secrets", headers, {
    name: `back-nav-${stamp}`,
    purpose: "openai",
    value: { kind: "api_key", api_key: "sk-e2e-stub-not-a-real-key" },
  });
  const model = await call(api, "/providers/model-profiles", headers, {
    label: `Back navigation model ${stamp}`,
    provider: "openai",
    model: "gpt-4.1-mini",
    secret_id: secret.id,
    base_url: `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`,
    api: "chat",
  });
  const agent = await call(api, "/agents", headers, {
    spec: {
      name: `E2E-BACK ${stamp}`,
      instructions: "Reply with exactly PONG and nothing else.",
      model_profile_id: model.id,
    },
  });
  await call(api, `/agents/${agent.id}/publish`, headers, {});
  const dataset = await call(api, "/datasets", headers, { name: `Back navigation ${stamp}` });
  await call(api, `/datasets/${dataset.id}/cases`, headers, {
    input: `Back navigation question ${stamp}`,
    checks: [{ type: "equals", value: "PONG" }],
  });
  const run = await call(api, `/agents/${agent.id}/eval-runs`, headers, {
    dataset_id: dataset.id,
    reruns: 0,
  });
  return {
    agent: String(agent.id),
    dataset: String(dataset.id),
    run: String(run.id),
    question: `Back navigation question ${stamp}`,
  };
}

const historyLength = (page: Page) => page.evaluate(() => window.history.length);

let seeded: Awaited<ReturnType<typeof seed>>;
test.beforeAll(async ({ browser }, testInfo) => {
  const context = await browser.newContext({
    storageState: AUTH_STATE,
    baseURL: testInfo.project.use.baseURL,
  });
  seeded = await seed(await context.newPage());
  await context.close();
});

test("a run opened from the agent's Evals tab returns there, by Back and by its arrow", async ({
  page,
}) => {
  const { agent, run } = seeded;
  await page.goto(`/agents/${agent}?tab=evals`);
  await page.locator(`a[href*="/agents/${agent}/evals/${run}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}/evals/${run}$`));

  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}\\?tab=evals$`));
  await expect(page.getByRole("tab", { name: "Evals" })).toHaveAttribute("aria-selected", "true");

  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/evals/${run}$`));
  const length = await historyLength(page);
  await page.getByRole("link", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}\\?tab=evals$`));
  await expect(page.getByRole("tab", { name: "Evals" })).toHaveAttribute("aria-selected", "true");
  // A step back, not a new entry: Forward still reaches the run.
  expect(await historyLength(page)).toBe(length);
});

test("a run opened from the dataset's Evals tab returns to that tab", async ({ page }) => {
  const { dataset, run } = seeded;
  await page.goto(`/datasets/${dataset}`);
  await page.getByRole("tab", { name: "Evals" }).click();
  await expect(page).toHaveURL(new RegExp(`/datasets/${dataset}\\?tab=evals$`));
  await page.locator(`a[href*="/evals/${run}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`/evals/${run}$`));

  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/datasets/${dataset}\\?tab=evals$`));
  await expect(page.getByRole("tab", { name: "Evals" })).toHaveAttribute("aria-selected", "true");

  await page.goForward();
  await page.getByRole("link", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/datasets/${dataset}\\?tab=evals$`));
});

test("a case opened from its dataset is a step Back closes", async ({ page }) => {
  const { dataset, question } = seeded;
  await page.goto(`/datasets/${dataset}`);
  await page.getByRole("button", { name: new RegExp(question) }).click();
  await expect(page.getByRole("dialog", { name: "Case" })).toBeVisible();
  await expect(page).toHaveURL(/[?&]case=/);

  await page.goBack();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/datasets/${dataset}$`));
  await expect(page.getByRole("tab", { name: "Cases" })).toHaveAttribute("aria-selected", "true");
});

test("Back from the Improve wizard returns to the agent", async ({ page }) => {
  const { agent } = seeded;
  await page.goto(`/agents/${agent}?tab=evals`);
  await page.getByRole("button", { name: "Improve", exact: true }).first().click();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}/improve/`));

  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}\\?tab=evals$`));
});

test("a run opened from a link falls back to its agent's Evals tab", async ({ page }) => {
  const { agent, run } = seeded;
  await page.goto(`/agents/${agent}/evals/${run}`);
  await page.getByRole("link", { name: "Back to the agent's evals" }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${agent}\\?tab=evals$`));
  await expect(page.getByRole("tab", { name: "Evals" })).toHaveAttribute("aria-selected", "true");
});
