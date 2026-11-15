import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, submitDialog } from "./helpers";
import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";

test.use({
  storageState: AUTH_STATE,
  viewport: { width: 320, height: 740 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

async function switchOrg(page: Page, name: string): Promise<void> {
  await page.getByRole("button", { name: "Toggle menu", exact: true }).click();
  await page.getByRole("button", { name: /^Switch organization/ }).click();
  await page.getByRole("menuitem", { name: new RegExp(name) }).click();
  await page.keyboard.press("Escape");
}

test("phone knowledge forms preserve a refused save, then index and search a file", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await page.goto("/rag");
  const serverName = `Embedding fixture ${Date.now().toString(36)}`;
  const createdServer = await page.request.post("/api/local-services", {
    data: {
      name: serverName,
      kind: "embedding",
      provider: "ollama",
      base_url: `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`,
    },
  });
  expect(createdServer.ok()).toBe(true);
  const server: { id: string } = await createdServer.json();
  await page.getByRole("button", { name: "New knowledge base", exact: true }).click();
  const create = page.getByRole("dialog");
  const name = `Knowledge journey ${Date.now().toString(36)}`;
  await create.getByLabel("Name", { exact: true }).fill(name);
  await create.getByLabel("Embedding provider", { exact: true }).click();
  await page.getByRole("option", { name: "Ollama", exact: true }).click();
  await create.getByLabel("Server", { exact: true }).click();
  await page.getByRole("option", { name: serverName, exact: true }).click();
  await submitDialog(page, {
    dialog: create,
    submit: create.getByRole("button", { name: "Create", exact: true }),
    path: "/api/kb",
  });
  const kb = await nowMatching(page.request, "/api/kb", (row) => row.name === name, name);
  const kbId = String(kb.id);
  await page.goto(`/rag/${kbId}?tab=ingestion`);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const ingestion = page.getByRole("dialog");
  await ingestion.getByLabel("Chunk size", { exact: true }).fill("1200");
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const writing = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route(`**/api/kb/${kbId}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    started();
    await held;
    await route.fulfill({ status: 403, json: { detail: "Controlled settings refusal" } });
  });
  await ingestion.getByRole("button", { name: "Save", exact: true }).click();
  await writing;
  await expect(ingestion.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
  await expect(ingestion.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(ingestion).toBeVisible();
  release();
  await expect(ingestion.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  await expect(ingestion.getByLabel("Chunk size", { exact: true })).toHaveValue("1200");
  await page.unroute(`**/api/kb/${kbId}`);
  await submitDialog(page, {
    dialog: ingestion,
    submit: ingestion.getByRole("button", { name: "Save", exact: true }),
    path: `/api/kb/${kbId}`,
    method: "PATCH",
  });
  await page.reload();
  await expect(page.getByRole("main")).toContainText("1,200 characters");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByRole("dialog").getByLabel("Chunk size", { exact: true })).toHaveValue(
    "1200",
  );
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  await page.goto(`/rag/${kbId}`);
  const policy =
    "The refund policy allows returns within 30 days. Contact support to request a refund.";
  const upload = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.includes(`/api/kb/${kbId}/`) &&
      response.request().method() === "POST",
  );
  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: "refund-policy.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(policy),
    });
  expect((await upload).ok()).toBe(true);
  await expect(page.getByRole("row").filter({ hasText: "refund-policy.txt" })).toContainText(
    "Done",
    { timeout: 45_000 },
  );
  await page.reload();
  await expect(page.getByRole("row").filter({ hasText: "refund-policy.txt" })).toContainText(
    "Done",
  );
  const fileRow = page.getByRole("row").filter({ hasText: "refund-policy.txt" });
  await fileRow.getByRole("button", { name: "Preview file", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(policy);
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  for (const label of ["Preview file", "Download file", "Remove document"]) {
    const action = await fileRow.getByRole("button", { name: label, exact: true }).boundingBox();
    expect(action!.x + action!.width).toBeLessThanOrEqual(320);
    expect(action?.width).toBeGreaterThanOrEqual(43.99);
  }
  const downloadPath = `**/api/kb/${kbId}/documents/*/download`;
  await page.route(downloadPath, (route) =>
    route.fulfill({ status: 403, json: { detail: "Controlled download refusal" } }),
  );
  await fileRow.getByRole("button", { name: "Download file", exact: true }).click();
  await expect(page.getByText("Controlled download refusal", { exact: true })).toBeVisible();
  await page.unroute(downloadPath);
  const downloading = page.waitForEvent("download");
  await fileRow.getByRole("button", { name: "Download file", exact: true }).click();
  const downloaded = await downloading;
  expect(downloaded.suggestedFilename()).toBe("refund-policy.txt");
  const downloadedPath = await downloaded.path();
  expect(downloadedPath).not.toBeNull();
  expect(await readFile(downloadedPath!, "utf8")).toBe(policy);
  await page.goto("/rag?tab=search");
  const query = page.getByRole("textbox", { name: "Search query", exact: true });
  await query.fill(policy);
  await page.getByRole("combobox", { name: "Search scope" }).click();
  await page.getByRole("option", { name, exact: true }).click();
  await page.route("**/api/rag/search", (route) =>
    route.fulfill({ status: 409, json: { detail: "Search temporarily refused" } }),
  );
  await page.getByRole("main").getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("main")).toContainText("Couldn't run the search");
  await page.unroute("**/api/rag/search");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("main")).toContainText(policy);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "refund-policy.txt", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(policy);
  await page.keyboard.press("Escape");
  await query.fill("Annual leave entitlement");
  await expect(page.getByRole("main").getByText(policy, { exact: true })).toHaveCount(0);
  expect((await page.request.delete(`/api/kb/${kbId}`)).ok()).toBe(true);
  expect((await page.request.delete(`/api/local-services/${server.id}`)).ok()).toBe(true);
});

test("phone organization forms save identity, budget, voice and retention", async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto("/orgs");
  const name = `Settings journey ${Date.now().toString(36)}`;
  await page.getByRole("button", { name: "New organization", exact: true }).click();
  const creation = page.getByRole("dialog");
  await creation.getByRole("textbox", { name: "Organization name", exact: true }).fill(name);
  await submitDialog(page, {
    dialog: creation,
    submit: creation.getByRole("button", { name: "Create", exact: true }),
    path: "/api/orgs",
  });
  const org = await nowMatching(page.request, "/api/orgs", (row) => row.name === name, name);
  await switchOrg(page, name);
  const path = `/orgs/${org.id}/members`;
  await page.goto(`${path}?tab=profile`);
  const field = page.getByRole("textbox", { name: "Organization name", exact: true });
  const edited = `${name} edited`;
  await field.fill(edited);
  const nameBounds = await field.boundingBox();
  expect(nameBounds?.width).toBeGreaterThan(200);
  const avatarBounds = await page
    .getByRole("button", { name: "Change organization avatar", exact: true })
    .boundingBox();
  expect(avatarBounds!.x + avatarBounds!.width).toBeLessThanOrEqual(320);
  const leave = () =>
    page
      .getByRole("navigation", { name: "Breadcrumb" })
      .getByRole("link", { name: "Organizations", exact: true })
      .click();
  await leave();
  const guard = page.getByRole("dialog", { name: "You have unsaved changes" });
  await guard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(field).toHaveValue(edited);
  await page.route(`**/api/orgs/${org.id}`, (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({ status: 409, json: { detail: "Organization changed elsewhere" } })
      : route.continue(),
  );
  await leave();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(guard).toBeHidden();
  await expect(field).toHaveValue(edited);
  await page.unroute(`**/api/orgs/${org.id}`);
  await leave();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await page.goto(`${path}?tab=governance`);
  const budget = page.getByRole("spinbutton", { name: "Limit (USD)", exact: true });
  await budget.fill("75.5");
  await page.getByRole("tab", { name: "Workspace", exact: true }).click();
  const length = page.getByRole("textbox", { name: "Max recording length", exact: true });
  await length.fill("8");
  await leave();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(/\/orgs$/);
  await page.goto(`${path}?tab=profile`);
  await expect(field).toHaveValue(edited);
  await expect(length).toHaveValue("8");
  await page.getByRole("tab", { name: "Budget and approvals", exact: true }).click();
  await expect(budget).toHaveValue("75.5");
  await page.goto(`/orgs/${org.id}/retention`);
  const runs = page.getByRole("spinbutton", { name: "Runs and their manifests", exact: true });
  await runs.fill("30");
  const back = () =>
    page
      .getByRole("navigation", { name: "Breadcrumb" })
      .getByRole("link", { name: "Members", exact: true })
      .click();
  await back();
  await guard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(runs).toHaveValue("30");
  await page.route(`**/api/orgs/${org.id}/retention`, (route) =>
    route.request().method() === "PUT"
      ? route.fulfill({ status: 403, json: { detail: "Controlled retention refusal" } })
      : route.continue(),
  );
  await back();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(guard).toBeHidden();
  await expect(runs).toHaveValue("30");
  await page.unroute(`**/api/orgs/${org.id}/retention`);
  await back();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/members$`));
  await page.goto(`/orgs/${org.id}/retention`);
  await expect(runs).toHaveValue("30");
  await page.goto(path);
  await page.getByRole("button", { name: "Invite teammate", exact: true }).click();
  const invitation = page.getByRole("dialog");
  await invitation
    .getByRole("textbox", { name: "Email address", exact: true })
    .fill("phone-review@example.invalid");
  const inviteSubmit = invitation.getByRole("button", {
    name: /Send invitation|Invite member|Send invite/,
    exact: false,
  });
  await expect(inviteSubmit).toBeVisible();
  await invitation.getByRole("button", { name: "Cancel", exact: true }).click();
  await switchOrg(page, "Personal");
  expect((await page.request.delete(`/api/orgs/${org.id}`)).ok()).toBe(true);
});

test("phone member actions stay in view and removal waits for confirmation", async ({ page }) => {
  const org = await nowMatching(
    page.request,
    "/api/orgs",
    (row) => row.is_personal === true,
    "personal organization",
  );
  const path = `/orgs/${org.id}/members`;
  const colleague = await nowMatching(
    page.request,
    `/api${path}`,
    (row) => row.email === "colleague@example.com",
    "seeded colleague",
  );
  await page.goto(path);
  const row = page.getByRole("row").filter({ hasText: "colleague@example.com" });
  await expect(row).toBeVisible();
  const remove = row.getByRole("button", { name: "Remove Colleague", exact: true });
  const forget = row.getByRole("button", {
    name: "Forget what agents know about Colleague",
    exact: true,
  });
  const role = row.getByRole("combobox", { name: "Role for colleague@example.com", exact: true });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 740 });
    for (const control of [remove, forget, role]) {
      const bounds = await control.boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      expect(bounds?.height).toBeGreaterThanOrEqual(43.99);
    }
  }
  await forget.click();
  await expect(page.getByRole("dialog")).toContainText("Colleague");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  let removals = 0;
  await page.route(`**/api${path}/${colleague.user_id}`, (route) => {
    if (route.request().method() !== "DELETE") return route.continue();
    removals += 1;
    return route.fulfill({ status: 403, json: { detail: "Controlled member removal refusal" } });
  });
  await remove.click();
  await expect(page.getByRole("dialog", { name: "Remove Colleague?", exact: true })).toBeVisible();
  expect(removals).toBe(0);
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  expect(removals).toBe(0);
  await remove.click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Remove Colleague", exact: true })
    .click();
  await expect.poll(() => removals).toBe(1);
  await expect(page.getByRole("dialog", { name: "Remove Colleague?", exact: true })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(row).toBeVisible();
});
