import type { APIRequestContext } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

async function create(api: APIRequestContext, path: string, data: object): Promise<string> {
  const response = await api.post(`/api${path}`, { data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null || !("id" in body) || typeof body.id !== "string")
    throw new Error(`No resource identity from ${path}`);
  return body.id;
}

test("choose an agent from a dataset, estimate and complete its eval", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
  await expect.poll(async () => (await page.request.get("/api/auth/me")).status()).toBe(200);
  const stamp = Date.now().toString(36);
  const name = `Picker agent ${stamp}`;
  const secret = await create(page.request, "/secrets", {
    name: `picker-${stamp}`,
    purpose: "openai",
    value: { kind: "api_key", api_key: "sk-e2e-stub-not-a-real-key" },
  });
  const model = await create(page.request, "/providers/model-profiles", {
    label: `Picker model ${stamp}`,
    provider: "openai",
    model: "gpt-4.1-mini",
    secret_id: secret,
    base_url: `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`,
    api: "chat",
  });
  const agent = await create(page.request, "/agents", {
    spec: {
      name,
      instructions: "Reply with exactly PONG-PICKER and nothing else.",
      model_profile_id: model,
    },
  });
  await create(page.request, `/agents/${agent}/publish`, {});
  const dataset = await create(page.request, "/datasets", { name: `Picker cases ${stamp}` });
  try {
    await page.goto(`/datasets/${dataset}?tab=evals`);
    await page.getByRole("button", { name: "Run evals", exact: true }).first().click();
    const dialog = page.getByRole("dialog").first();
    await expect(dialog.getByRole("combobox", { name: "Dataset", exact: true })).toContainText(
      `Picker cases ${stamp}`,
    );
    await expect(dialog.getByText(/This dataset has no cases yet/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Run evals", exact: true })).toBeDisabled();
    await dialog.getByRole("link", { name: "Open cases", exact: true }).click();
    await expect(dialog).toBeHidden();
    await page.waitForURL(`**/datasets/${dataset}?tab=cases`);
    await create(page.request, `/datasets/${dataset}/cases`, {
      input: "Say the word.",
      checks: [{ type: "equals", value: "PONG-PICKER" }],
    });
    const scoring = await page.request.put(`/api/datasets/${dataset}/scoring`, {
      data: {
        checks: { enabled: true, required: true },
        judge: { enabled: false },
        reference: { enabled: false },
        trajectory: { enabled: false },
      },
    });
    expect(scoring.ok(), await scoring.text()).toBeTruthy();
    await page.goto(`/datasets/${dataset}?tab=evals`);
    await page.getByRole("button", { name: "Run evals", exact: true }).first().click();
    await page.setViewportSize({ width: 320, height: 568 });
    await dialog.getByRole("combobox", { name: "Agent", exact: true }).click();
    await expect
      .poll(async () =>
        page.locator("[cmdk-list]").evaluate((list) => {
          const panel = list.closest("[data-radix-popper-content-wrapper]");
          if (!panel) throw new Error("Agent options have no popover");
          return list.getBoundingClientRect().bottom <= panel.getBoundingClientRect().bottom + 1;
        }),
      )
      .toBe(true);
    await page.getByPlaceholder("Search agents").fill(name);
    const option = page.getByRole("option", { name, exact: true });
    await expect(option.locator(`[data-agent-avatar="${agent}"]`)).toBeVisible();
    await option.click();
    await expect(dialog.getByRole("radio", { name: /v1 alone/ })).toBeChecked();
    const start = dialog.getByRole("button", { name: /^Run for/ });
    await expect(start).toBeEnabled();
    await start.click();
    await page.waitForURL(new RegExp(`/agents/${agent}/evals/[^/?]+$`));
    const runId = new URL(page.url()).pathname.split("/").pop();
    await expect
      .poll(async () => {
        const response = await page.request.get(`/api/eval-runs/${runId}`);
        expect(response.ok(), await response.text()).toBeTruthy();
        const body: unknown = await response.json();
        return typeof body === "object" && body !== null && "status" in body ? body.status : null;
      })
      .toBe("completed");
    await expect(page.getByText("100%", { exact: true }).first()).toBeVisible();
  } finally {
    for (const path of [
      `/datasets/${dataset}`,
      `/agents/${agent}`,
      `/providers/model-profiles/${model}`,
      `/secrets/${secret}`,
    ]) {
      const response = await page.request.delete(`/api${path}`);
      expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    }
  }
});
