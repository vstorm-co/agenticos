import { expect, test } from "./fixtures";
import { AUTH_STATE, FAKE_KEY_LABEL, STUB_MODEL_ENDPOINT, nowMatching, rowsAt } from "./helpers";
import type { APIResponse } from "@playwright/test";

test.use({
  actionTimeout: 15_000,
  storageState: AUTH_STATE,
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

async function createdId(response: APIResponse): Promise<string> {
  expect(response.ok(), `${response.url()} answered ${response.status()}`).toBe(true);
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    !("id" in value) ||
    typeof value.id !== "string"
  )
    throw new Error("Created resource has no id");
  return value.id;
}

test("context overrides persist and compact app sharing preserves optional settings and refused drafts", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const stamp = Date.now().toString(36);
  const cleanup: string[] = [];
  let release: (() => void) | undefined;
  try {
    const contextName = `layout-policy-${stamp}`;
    const contextId = await createdId(
      await page.request.post("/api/context", {
        data: {
          name: contextName,
          description: "Company policy and customer terminology.",
          content: "Use concise answers.",
          mode: "inject",
        },
      }),
    );
    cleanup.push(`/api/context/${contextId}`);
    const secret = (await rowsAt(page.request, "/api/secrets")).find(
      (row) => row.name === FAKE_KEY_LABEL,
    );
    expect(secret, "the stub key must be seeded").toBeDefined();
    const profileId = await createdId(
      await page.request.post("/api/providers/model-profiles", {
        data: {
          label: `Layout review ${stamp}`,
          provider: "openai",
          model: "gpt-4.1-mini",
          secret_id: secret?.id,
          base_url: STUB_MODEL_ENDPOINT,
        },
      }),
    );
    cleanup.push(`/api/providers/model-profiles/${profileId}`);
    const spec = {
      name: `Layout review ${stamp}`,
      instructions: "Follow the demo instructions.",
      model_profile_id: profileId,
      context_ids: [contextId],
      capabilities: [{ id: "context" }, { id: "artifacts" }],
    };
    const agentId = await createdId(await page.request.post("/api/agents", { data: { spec } }));
    cleanup.push(`/api/agents/${agentId}`);
    expect((await page.request.put(`/api/agents/${agentId}/draft`, { data: { spec } })).ok()).toBe(
      true,
    );
    expect((await page.request.post(`/api/agents/${agentId}/publish`, { data: {} })).ok()).toBe(
      true,
    );
    const title = `Discovery brief ${stamp}`;
    const args = {
      name: `layout-brief-${stamp}`,
      title,
      content:
        "<!doctype html><html><body><h1>Discovery brief</h1><p>Layout review fixture.</p></body></html>",
    };
    const prompt = `Publish the page. CALL-TOOL:publish_artifact:${Buffer.from(JSON.stringify(args)).toString("base64url")}`;
    expect(
      (
        await page.request.post(`/api/agents/${agentId}/run`, { data: { prompt }, timeout: 90_000 })
      ).ok(),
    ).toBe(true);
    const app = await nowMatching(page.request, "/api/apps", (row) => row.title === title, title);
    if (typeof app.id !== "string") throw new Error("Published app has no id");
    cleanup.push(`/api/apps/${app.id}`);

    await page.goto(`/agents/${agentId}`);
    await page.getByRole("tab", { name: "Toolbox", exact: true }).click();
    await page.getByRole("button", { name: "Context settings", exact: true }).click();
    const context = page.getByRole("dialog");
    await expect(context.getByRole("checkbox", { name: contextName })).toBeChecked();
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname === `/api/agents/${agentId}/draft` &&
        response.ok(),
    );
    await context.getByRole("combobox", { name: `How ${contextName} is used` }).click();
    await page.getByRole("option", { name: "linked", exact: true }).click();
    await saved;
    await page.reload();
    await page.getByRole("tab", { name: "Toolbox", exact: true }).click();
    await page.getByRole("button", { name: "Context settings", exact: true }).click();
    await expect(context.getByRole("combobox", { name: `How ${contextName} is used` })).toHaveText(
      "linked",
    );
    await expect(context.getByRole("checkbox", { name: contextName })).toBeChecked();
    await page.keyboard.press("Escape");

    await page.goto(`/apps/${app.id}`);
    await page.getByRole("button", { name: "App controls", exact: true }).click();
    await page.getByRole("button", { name: "Share", exact: true }).click();
    const share = page.getByRole("dialog");
    await expect(
      share.getByRole("heading", { name: "People with access", exact: true }),
    ).toBeVisible();
    const options = share
      .locator("details")
      .filter({ has: page.locator("summary", { hasText: "Link settings" }) });
    await expect(options).not.toHaveAttribute("open");
    await expect(share.getByLabel("Sites that may embed it")).toBeHidden();
    await share.getByRole("button", { name: "Create a public link", exact: true }).click();
    await expect(share.getByLabel("Public link", { exact: true })).toBeVisible();
    await options.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(options).toHaveAttribute("open");
    const origins = share.getByLabel("Sites that may embed it");
    await origins.fill("https://intranet.example.com");
    await share.getByLabel("Stops opening after").fill("2030-12-31");
    await share.getByRole("combobox", { name: "Shows", exact: true }).click();
    await page.getByRole("option", { name: "v1", exact: true }).click();
    await options.locator("summary").click();
    await options.locator("summary").click();
    await expect(origins).toHaveValue("https://intranet.example.com");
    let began!: () => void;
    const started = new Promise<void>((resolve) => {
      began = resolve;
    });
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const path = `**/api/apps/${app.id}/public-link`;
    await page.route(path, async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      began();
      await held;
      await route.fulfill({ status: 403, json: { detail: "Controlled sharing settings refusal" } });
    });
    await share.getByRole("button", { name: "Save link settings", exact: true }).click();
    await started;
    await expect(origins).toBeDisabled();
    await options.locator("summary").click();
    await expect(options).toHaveAttribute("open");
    release?.();
    await expect(origins).toBeEnabled();
    await expect(origins).toHaveValue("https://intranet.example.com");
    await page.unroute(path);
    await share.getByRole("button", { name: "Save link settings", exact: true }).click();
    await expect(share.getByText("1 embedding site", { exact: true })).toBeVisible();
    await options.locator("summary").click();
    await share.getByLabel("Password", { exact: true }).fill("demo-layout-password");
    await share.getByRole("button", { name: "Set password", exact: true }).click();
    await expect(share.getByText("Password protected", { exact: true })).toBeVisible();
    await expect(options).not.toHaveAttribute("open");
    await page.reload();
    await page.getByRole("button", { name: "App controls", exact: true }).click();
    await page.getByRole("button", { name: "Share", exact: true }).click();
    await expect(share.getByText("Password protected", { exact: true })).toBeVisible();
    await options.locator("summary").click();
    await expect(share.getByLabel("Password", { exact: true })).toHaveValue("");
    await expect(share.getByLabel("Sites that may embed it")).toHaveValue(
      "https://intranet.example.com",
    );
    await expect(share.getByLabel("Stops opening after")).toHaveValue("2030-12-31");
    await expect(share.getByRole("combobox", { name: "Shows", exact: true })).toHaveText("v1");
    await options.locator("summary").click();
    await share.getByRole("button", { name: "Turn off", exact: true }).click();
    await expect(
      share.getByRole("button", { name: "Create a public link", exact: true }),
    ).toBeVisible();
  } finally {
    release?.();
    for (const path of cleanup.reverse())
      expect((await page.request.delete(path)).ok(), `cleanup ${path}`).toBe(true);
  }
});
