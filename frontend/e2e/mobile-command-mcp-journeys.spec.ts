import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, submitDialog, SEEDED_ORG_MCP_URL } from "./helpers";
import { join } from "node:path";

test.use({
  storageState: AUTH_STATE,
  viewport: { width: 320, height: 740 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

test("phone command editing guards drafts, serializes writes and confirms removal", async ({
  page,
}) => {
  const name = `review-checklist-${Date.now().toString(36)}`;
  let id: string | undefined;
  try {
    await page.goto("/settings/slash-commands");
    await page.getByRole("button", { name: "New command", exact: true }).click();
    let editor = page.getByRole("dialog");
    await editor.getByLabel("Name", { exact: true }).fill(name);
    await editor
      .getByLabel("Prompt", { exact: true })
      .fill("Review the changes, list open questions and prepare a short checklist.");
    await submitDialog(page, {
      dialog: editor,
      submit: editor.getByRole("button", { name: "Create", exact: true }),
      path: "/api/me/slash-commands",
    });
    const record = await nowMatching(
      page.request,
      "/api/me/slash-commands",
      (row) => row.name === name,
      name,
    );
    id = String(record.id);
    await page.reload();
    const row = page.getByRole("listitem").filter({ hasText: `/${name}` });
    await row.scrollIntoViewIfNeeded();
    const createBounds = await page
      .getByRole("button", { name: "New command", exact: true })
      .boundingBox();
    expect(createBounds).not.toBeNull();
    expect(createBounds!.x + createBounds!.width).toBeLessThanOrEqual(320);
    const heading = await page
      .getByRole("heading", { name: "Your custom commands", exact: true })
      .boundingBox();
    expect(createBounds!.y).toBeGreaterThanOrEqual(heading!.y + heading!.height);
    for (const target of [
      row.getByRole("button", { name: `Edit /${name}`, exact: true }),
      row.getByRole("button", { name: `Delete /${name}`, exact: true }),
      row.getByRole("switch"),
    ]) {
      const bounds = await target.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.width).toBeGreaterThanOrEqual(44);
      expect(bounds!.height).toBeGreaterThanOrEqual(44);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
    }
    if (process.env.UI_AUDIT_SHOTS)
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "command-actions-mobile-after.png"),
      });
    await row.getByRole("button", { name: `Edit /${name}`, exact: true }).click();
    editor = page.getByRole("dialog");
    await editor.getByLabel("Prompt", { exact: true }).fill("Updated command prompt.");
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "You have unsaved changes", exact: true });
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    await expect(editor.getByLabel("Prompt", { exact: true })).toHaveValue(
      "Updated command prompt.",
    );
    await page.setViewportSize({ width: 320, height: 568 });
    await expect
      .poll(async () => {
        const bounds = await editor
          .getByRole("button", { name: "Save", exact: true })
          .boundingBox();
        return bounds === null ? Infinity : bounds.y + bounds.height;
      })
      .toBeLessThanOrEqual(568);
    const saveBounds = await editor
      .getByRole("button", { name: "Save", exact: true })
      .boundingBox();
    expect(saveBounds!.y).toBeGreaterThanOrEqual(0);
    await page.setViewportSize({ width: 320, height: 740 });
    let release!: () => void;
    let started!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const writing = new Promise<void>((resolve) => {
      started = resolve;
    });
    await page.route(`**/api/me/slash-commands/${id}`, async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      started();
      await held;
      await route.fulfill({ status: 403, json: { detail: "Controlled command refusal" } });
    });
    await editor.getByRole("button", { name: "Save", exact: true }).click();
    await writing;
    await expect(editor.getByLabel("Prompt", { exact: true })).toBeDisabled();
    await expect(editor.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(editor).toBeVisible();
    if (process.env.UI_AUDIT_SHOTS)
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "command-pending-mobile-after.png"),
      });
    release();
    await expect(editor.getByLabel("Prompt", { exact: true })).toBeEnabled();
    await expect(editor.getByLabel("Prompt", { exact: true })).toHaveValue(
      "Updated command prompt.",
    );
    await page.unroute(`**/api/me/slash-commands/${id}`);
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        response.url().endsWith(`/api/me/slash-commands/${id}`),
    );
    await guard.getByRole("button", { name: "Save", exact: true }).click();
    expect((await saved).ok()).toBe(true);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.reload();
    await expect(row).toContainText("Updated command prompt.");
    const toggle = row.getByRole("switch");
    const toggled = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        response.url().endsWith(`/api/me/slash-commands/${id}`),
    );
    await toggle.click();
    expect((await toggled).ok()).toBe(true);
    await expect(toggle).not.toBeChecked();
    await page.reload();
    await expect(toggle).not.toBeChecked();
    let deletes = 0;
    await page.route(`**/api/me/slash-commands/${id}`, async (route) => {
      if (route.request().method() !== "DELETE") return route.continue();
      deletes++;
      if (deletes === 1)
        return route.fulfill({ status: 403, json: { detail: "Controlled removal refusal" } });
      await route.continue();
    });
    await row.getByRole("button", { name: `Delete /${name}`, exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
    expect(deletes).toBe(0);
    await row.getByRole("button", { name: `Delete /${name}`, exact: true }).click();
    const confirm = page.getByRole("dialog");
    if (process.env.UI_AUDIT_SHOTS)
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "command-delete-mobile-after.png"),
      });
    const denied = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        response.url().endsWith(`/api/me/slash-commands/${id}`),
    );
    await confirm.getByRole("button", { name: "Delete", exact: true }).click();
    expect((await denied).status()).toBe(403);
    await expect(confirm).toBeVisible();
    const removed = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        response.url().endsWith(`/api/me/slash-commands/${id}`),
    );
    await confirm.getByRole("button", { name: "Delete", exact: true }).click();
    expect((await removed).ok()).toBe(true);
    await expect(confirm).toHaveCount(0);
    await expect(row).toHaveCount(0);
    id = undefined;
  } finally {
    if (id) await page.request.delete(`/api/me/slash-commands/${id}`);
  }
});

test("phone MCP form freezes a refused write, retries and persists configuration", async ({
  page,
}) => {
  const prefix = `workspace-${Date.now().toString(36)}`;
  let id: string | undefined;
  try {
    await page.route("**/api/me/mcp-connections/probe", (route) =>
      route.fulfill({ json: { sign_in: false, registers_clients: false } }),
    );
    // Exercise stored configuration without contacting an external MCP provider.
    await page.route("**/api/mcp-connections/*/test", (route) =>
      route.fulfill({ json: { ok: false, tools: [], error: "Controlled probe refusal" } }),
    );
    await page.goto("/mcp-servers");
    await page.getByRole("button", { name: "Add a custom server", exact: true }).click();
    const editor = page
      .getByRole("dialog")
      .filter({ has: page.getByLabel("Server URL", { exact: true }) });
    await editor.getByLabel("Name", { exact: true }).fill("Company workspace");
    await editor.getByLabel("Tool prefix", { exact: true }).fill(prefix);
    await editor.getByLabel("Server URL", { exact: true }).fill(SEEDED_ORG_MCP_URL);
    await editor.getByRole("radio", { name: "None", exact: true }).click();
    let release!: () => void;
    let started!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const writing = new Promise<void>((resolve) => {
      started = resolve;
    });
    await page.route("**/api/mcp-connections", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      started();
      await held;
      await route.fulfill({ status: 403, json: { detail: "Controlled connection refusal" } });
    });
    await editor.getByRole("button", { name: "Connect & check", exact: true }).click();
    await writing;
    await expect(editor.getByLabel("Name", { exact: true })).toBeDisabled();
    await expect(editor.getByLabel("Server URL", { exact: true })).toBeDisabled();
    await expect(editor.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(editor).toBeVisible();
    await editor.getByLabel("Name", { exact: true }).scrollIntoViewIfNeeded();
    if (process.env.UI_AUDIT_SHOTS)
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "mcp-pending-mobile-after.png"),
      });
    release();
    await expect(editor.getByLabel("Name", { exact: true })).toBeEnabled();
    await expect(editor.getByLabel("Tool prefix", { exact: true })).toHaveValue(prefix);
    await page.unroute("**/api/mcp-connections");
    await submitDialog(page, {
      dialog: editor,
      submit: editor.getByRole("button", { name: "Connect & check", exact: true }),
      path: "/api/mcp-connections",
    });
    const saved = await nowMatching(
      page.request,
      "/api/mcp-connections",
      (row) => row.name === prefix,
      prefix,
    );
    id = String(saved.id);
    expect(saved.label).toBe("Company workspace");
    expect(saved.url).toBe(SEEDED_ORG_MCP_URL);
    await page.reload();
    await page.getByRole("textbox", { name: "Search servers…", exact: true }).fill(prefix);
    const card = page.getByRole("group", { name: prefix, exact: true });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: /^Manage / }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "More for Company workspace", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
    await expect(editor.getByLabel("Name", { exact: true })).toHaveValue("Company workspace");
    await editor.getByLabel("Name", { exact: true }).fill("Reviewed workspace");
    await submitDialog(page, {
      dialog: editor,
      submit: editor.getByRole("button", { name: "Save", exact: true }),
      path: `/api/mcp-connections/${id}`,
      method: "PATCH",
    });
    await page.reload();
    const reread = await nowMatching(
      page.request,
      "/api/mcp-connections",
      (row) => row.id === id && row.label === "Reviewed workspace",
      "updated workspace",
    );
    expect(reread.name).toBe(prefix);
  } finally {
    if (id) expect((await page.request.delete(`/api/mcp-connections/${id}`)).ok()).toBe(true);
  }
});

test("phone OAuth start keeps a refused draft and retries the redirect", async ({ page }) => {
  await page.route("**/api/me/mcp-connections/probe", (route) =>
    route.fulfill({ json: { sign_in: true, registers_clients: true } }),
  );
  await page.goto("/mcp-servers");
  await page.getByRole("button", { name: "Add a custom server", exact: true }).click();
  const editor = page.getByRole("dialog");
  await editor.getByLabel("Name", { exact: true }).fill("Company workspace");
  await editor.getByLabel("Server URL", { exact: true }).fill(SEEDED_ORG_MCP_URL);
  await editor.getByRole("radio", { name: "OAuth", exact: true }).click();
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const writing = new Promise<void>((resolve) => {
    started = resolve;
  });
  let calls = 0;
  await page.route("**/api/mcp-connections/oauth/start", async (route) => {
    calls++;
    if (calls === 1) {
      started();
      await held;
      return route.fulfill({ status: 403, json: { detail: "Controlled sign-in refusal" } });
    }
    // A local stand-in for the consent destination; no provider grant is made.
    return route.fulfill({
      json: { authorization_url: new URL("/legal/privacy", page.url()).href },
    });
  });
  await editor.getByRole("button", { name: "Connect & check", exact: true }).click();
  await writing;
  await expect(editor.getByLabel("Name", { exact: true })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(editor).toBeVisible();
  release();
  await expect(editor.getByLabel("Name", { exact: true })).toBeEnabled();
  await expect(editor.getByLabel("Name", { exact: true })).toHaveValue("Company workspace");
  await expect(editor.getByLabel("Server URL", { exact: true })).toHaveValue(SEEDED_ORG_MCP_URL);
  await expect(page.getByText("Controlled sign-in refusal", { exact: true })).toBeVisible();
  await editor.getByLabel("Name", { exact: true }).scrollIntoViewIfNeeded();
  if (process.env.UI_AUDIT_SHOTS) {
    await page
      .getByText("Controlled sign-in refusal", { exact: true })
      .waitFor({ state: "hidden" });
    await page.screenshot({
      path: join(process.env.UI_AUDIT_SHOTS, "mcp-oauth-refusal-mobile-after.png"),
    });
  }
  await editor.getByRole("button", { name: "Connect & check", exact: true }).click();
  await expect(page).toHaveURL(/\/legal\/privacy$/);
  expect(calls).toBe(2);
});
