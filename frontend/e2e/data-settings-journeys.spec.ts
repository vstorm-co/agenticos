import { expect, test } from "./fixtures";
import { AUTH_STATE, nowListed, nowMatching, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE });

function recordValues(row: Record<string, unknown>): unknown[] {
  return typeof row.values === "object" && row.values !== null ? Object.values(row.values) : [];
}

test("CSV mapping preserves the chosen value across import, views and reload", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/tables");
  await page.getByRole("button", { name: "New table", exact: true }).first().click();
  const create = page.getByRole("dialog");
  const name = `CSV journey ${Date.now().toString(36)}`;
  await create.getByRole("textbox", { name: /^Name/ }).fill(name);
  await submitDialog(page, {
    dialog: create,
    submit: create.getByRole("button", { name: "Create table", exact: true }),
    path: "/api/tables",
  });
  await nowListed(page.request, "/api/tables", "name", name);
  await expect(page).toHaveURL(/\/tables\/[^/?]+$/);
  const tablePath = new URL(page.url()).pathname;
  await page.getByRole("button", { name: "More actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Import", exact: true }).click();
  const importer = page.getByRole("dialog");
  await page.setViewportSize({ width: 390, height: 844 });
  await importer.getByLabel("Choose a CSV file").setInputFiles({
    name: "duplicates.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Name,name\nPreserved value,Overwritten value\n"),
  });
  await expect(importer.getByRole("button", { name: "Import 1 row" })).toBeDisabled();
  await expect(importer.getByRole("alert")).toContainText("Map each table column only once");
  await importer.getByRole("combobox", { name: "Where name goes", exact: true }).click();
  await page.getByRole("option", { name: "Don't import", exact: true }).click();
  await importer.getByRole("button", { name: "Import 1 row", exact: true }).click();
  await expect(importer).toContainText("1 record added.");
  await importer.getByRole("button", { name: "Close", exact: true }).first().click();
  const record = await nowMatching(
    page.request,
    `/api${tablePath}/records`,
    (row) => recordValues(row).includes("Preserved value"),
    "the preserved CSV value",
  );
  expect(recordValues(record)).not.toContain("Overwritten value");
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const view of ["List", "Table"]) {
    await page.getByRole("tab", { name: view, exact: true }).click();
    await expect(
      page.getByRole("main").getByText("Preserved value", { exact: true }),
    ).toBeVisible();
  }
  await page.reload();
  await expect(page.getByRole("main").getByText("Preserved value", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "List", exact: true }).click();
  await page.getByRole("button", { name: /Preserved value/ }).click();
  const sheet = page.getByRole("dialog");
  const written = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      new URL(response.url()).pathname.includes(`${tablePath}/records/`),
  );
  await sheet.getByRole("textbox", { name: "Name", exact: true }).fill("Reviewed value");
  await page.keyboard.press("Tab");
  expect((await written).ok()).toBe(true);
  await nowMatching(
    page.request,
    `/api${tablePath}/records`,
    (row) => row.id === record.id && recordValues(row).includes("Reviewed value"),
    "the edited CSV record",
  );
  await sheet.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Add record", exact: true }).first().click();
  const add = page.getByRole("dialog");
  await add.getByRole("textbox", { name: "Name", exact: true }).fill("Manual record");
  await submitDialog(page, {
    dialog: add,
    submit: add.getByRole("button", { name: "Add record", exact: true }),
    path: `/api${tablePath}/records`,
  });
  await nowMatching(
    page.request,
    `/api${tablePath}/records`,
    (row) => recordValues(row).includes("Manual record"),
    "the manually added record",
  );
  await page.reload();
  await expect(page.getByRole("main")).toContainText("Reviewed value");
  await expect(page.getByRole("main")).toContainText("Manual record");
  await page.setViewportSize({ width: 320, height: 740 });
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  const filters = page.getByRole("dialog");
  await filters.getByRole("button", { name: "Add condition", exact: true }).click();
  for (const label of ["Column", "Operator"]) {
    const control = filters.getByRole("combobox", { name: label, exact: true });
    const bounds = await control.boundingBox();
    expect(bounds, `${label} must remain visible on a narrow phone`).not.toBeNull();
    expect(bounds?.width).toBeGreaterThan(200);
  }
  await filters.getByPlaceholder("Value", { exact: true }).fill("Reviewed");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("main")).toContainText("Reviewed value");
  await expect(page.getByRole("main")).not.toContainText("Manual record");
  await page.getByRole("button", { name: "Filter", exact: false }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Clear all", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("main")).toContainText("Manual record");
  expect((await page.request.post(`/api${tablePath}/archive`)).ok()).toBe(true);
});

test("a knowledge base indexes a file, searches its source and recovers from a refusal", async ({
  page,
}) => {
  test.setTimeout(90_000);
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

test("organization name, budget and voice settings survive guarded navigation", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.goto("/orgs");
  const name = `Settings journey ${Date.now().toString(36)}`;
  const created = await page.request.post("/api/orgs", { data: { name } });
  expect(created.ok()).toBe(true);
  const org: { id: string } = await created.json();
  await page.reload();
  await page.getByRole("button", { name: /^Switch organization/ }).click();
  await page.getByRole("menuitem", { name: new RegExp(name) }).click();
  const path = `/orgs/${org.id}/members`;
  await page.goto(`${path}?tab=profile`);
  const field = page.getByRole("textbox", { name: "Organization name", exact: true });
  const edited = `${name} edited`;
  await field.fill(edited);
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
  await page.getByRole("button", { name: /^Switch organization/ }).click();
  await page.getByRole("menuitem", { name: /Personal/, exact: false }).click();
  expect((await page.request.delete(`/api/orgs/${org.id}`)).ok()).toBe(true);
});
