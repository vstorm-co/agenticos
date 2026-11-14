import type { APIRequestContext, Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, SEEDED_AGENT_NAME, submitDialog } from "./helpers";

async function heldRefusal(page: Page, path: string, method: "POST" | "DELETE") {
  const held = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const pattern = `**${path}`;
  await page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.continue();
    started.resolve();
    await held.promise;
    await route.fulfill({ status: 403, json: { detail: "Controlled API key refusal" } });
  });
  return {
    started: started.promise,
    release: () => held.resolve(),
    remove: () => page.unroute(pattern),
  };
}

for (const device of [
  { name: "desktop", viewport: { width: 1440, height: 1000 }, phone: false },
  { name: "phone", viewport: { width: 320, height: 568 }, phone: true },
] as const) {
  test.describe(device.name, () => {
    test.use({
      storageState: AUTH_STATE,
      viewport: device.viewport,
      isMobile: device.phone,
      hasTouch: device.phone,
      actionTimeout: 15_000,
      reducedMotion: "reduce",
    });
    test("create, copy, scoped use and revocation retain refused choices", async ({
      page,
      context,
      playwright,
    }) => {
      test.setTimeout(120_000);
      const name = `UI key flow ${device.name} ${Date.now().toString(36)}`;
      const backend = process.env.E2E_BACKEND_URL ?? "http://localhost:8000";
      let client: APIRequestContext | undefined;
      let id: string | undefined;
      let release: (() => void) | undefined;
      try {
        await page.goto("/settings/api-keys");
        await expect(page.getByRole("button", { name: "Create key", exact: true })).toBeVisible();
        const catalog = await page.request.get("/api/api-keys/scopes");
        expect(catalog.ok(), `scope catalog answered ${catalog.status()}`).toBe(true);
        await context.grantPermissions(["clipboard-read", "clipboard-write"]);
        await page.getByRole("button", { name: "Copy", exact: true }).click();
        const baseUrl = await page.evaluate(() => navigator.clipboard.readText());
        expect(baseUrl === backend).toBe(true);
        client = await playwright.request.newContext({ baseURL: baseUrl });
        await page.getByRole("button", { name: "Create key", exact: true }).click();
        const dialog = page.getByRole("dialog");
        await dialog.getByLabel("Name", { exact: true }).fill(name);
        await dialog.getByRole("combobox", { name: "Access", exact: true }).click();
        await page.getByRole("option", { name: "Custom", exact: true }).click();
        const search = dialog.getByLabel("Find a permission", { exact: true });
        await search.fill("agents:view");
        const permission = dialog.getByRole("checkbox", { name: "agents:view", exact: true });
        await permission.check();
        await search.fill("collections:view");
        await expect(permission).toHaveCount(0);
        await search.fill("agents:view");
        await expect(permission).toBeChecked();
        await dialog.getByRole("combobox", { name: "Expires", exact: true }).click();
        await page.getByRole("option", { name: "In 30 days", exact: true }).click();
        const create = dialog.getByRole("button", { name: "Create", exact: true });
        const bounds = await create.boundingBox();
        expect(bounds).not.toBeNull();
        if (bounds) expect(bounds.y + bounds.height).toBeLessThanOrEqual(device.viewport.height);
        const held = await heldRefusal(page, "/api/api-keys", "POST");
        release = held.release;
        await create.click();
        await held.started;
        await expect(dialog.getByLabel("Name", { exact: true })).toBeDisabled();
        await expect(search).toBeDisabled();
        await expect(permission).toBeDisabled();
        await expect(dialog.getByRole("combobox", { name: "Access", exact: true })).toBeDisabled();
        await expect(dialog.getByRole("combobox", { name: "Expires", exact: true })).toBeDisabled();
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
        await page.keyboard.press("Escape");
        await expect(dialog).toBeVisible();
        held.release();
        await expect(search).toBeEnabled();
        await held.remove();
        await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(name);
        await expect(permission).toBeChecked();
        await expect(dialog.getByRole("combobox", { name: "Expires", exact: true })).toContainText(
          "In 30 days",
        );
        // This create advances to the one-time reveal rather than closing the dialog.
        // Wait for the write and that transition; submitDialog expects a closed dialog.
        const answered = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === "/api/api-keys" &&
            response.request().method() === "POST" &&
            response.status() !== 401,
        );
        await create.click();
        const response = await answered;
        expect(response.ok()).toBe(true);
        const created: unknown = await response.json();
        if (
          typeof created !== "object" ||
          created === null ||
          !("id" in created) ||
          typeof created.id !== "string"
        )
          throw new Error("Missing created key id");
        id = created.id;
        await expect(
          dialog.getByRole("heading", { name: "Copy your key", exact: true }),
        ).toBeVisible();
        const row = await nowMatching(
          page.request,
          "/api/api-keys",
          (key) => key.name === name,
          "created API key",
        );
        if (typeof row.id !== "string") throw new Error("Missing created key id");
        expect(row.id === id).toBe(true);
        expect("key" in row).toBe(false);
        expect(row.scopes).toEqual(["agents:view"]);
        expect(typeof row.expires_at === "string").toBe(true);
        const secret = await dialog.getByLabel(name, { exact: true }).inputValue();
        expect(secret.startsWith("aos_")).toBe(true);
        await context.grantPermissions(["clipboard-read", "clipboard-write"]);
        await dialog.getByRole("button", { name: "Copy", exact: true }).click();
        const copied = await page.evaluate(() => navigator.clipboard.readText());
        expect(copied === secret).toBe(true);
        const headers = { Authorization: `Bearer ${secret}` };
        const allowed = await client.get("/api/v1/agents", { headers });
        expect(allowed.status()).toBe(200);
        const agents: unknown = await allowed.json();
        if (
          typeof agents !== "object" ||
          agents === null ||
          !("items" in agents) ||
          !Array.isArray(agents.items)
        )
          throw new Error("Missing agent listing");
        expect(
          agents.items.some(
            (item: unknown) =>
              typeof item === "object" &&
              item !== null &&
              "name" in item &&
              item.name === SEEDED_AGENT_NAME,
          ),
        ).toBe(true);
        expect((await client.get("/api/v1/rag/collections", { headers })).status()).toBe(403);
        await dialog.getByRole("button", { name: "Done", exact: true }).click();
        await expect(dialog).toBeHidden();
        await page.getByRole("button", { name: "Create key", exact: true }).click();
        await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue("");
        await expect(dialog.getByRole("combobox", { name: "Access", exact: true })).toContainText(
          "Read-only",
        );
        await expect(dialog.getByRole("combobox", { name: "Expires", exact: true })).toContainText(
          "In 90 days",
        );
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
        const listSearch = page.getByPlaceholder("Search API keys…");
        await listSearch.fill("definitely-unmatched-key");
        await expect(page.getByText("No matching API keys", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: "Clear search", exact: true }).last().click();
        await listSearch.fill(name);
        const record = device.phone
          ? page
              .getByRole("listitem")
              .filter({ has: page.getByRole("heading", { name, exact: true }) })
          : page.getByRole("row").filter({ hasText: name });
        await expect(record).toBeVisible();
        await record.getByRole("button", { name: "Revoke", exact: true }).click();
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(record.getByText("Active", { exact: true })).toBeVisible();
        await record.getByRole("button", { name: "Revoke", exact: true }).click();
        const revoked = await heldRefusal(page, `/api/api-keys/${id}`, "DELETE");
        release = revoked.release;
        await dialog.getByRole("button", { name: "Revoke", exact: true }).click();
        await revoked.started;
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
        revoked.release();
        await expect(dialog.getByRole("button", { name: "Revoke", exact: true })).toBeEnabled();
        await revoked.remove();
        await expect(dialog).toBeVisible();
        await submitDialog(page, {
          dialog,
          submit: dialog.getByRole("button", { name: "Revoke", exact: true }),
          path: `/api/api-keys/${id}`,
          method: "DELETE",
        });
        await expect(record.getByText("Revoked", { exact: true })).toBeVisible();
        expect((await client.get("/api/v1/agents", { headers })).status()).toBe(401);
        await page.reload();
        await page.getByPlaceholder("Search API keys…").fill(name);
        await expect(record.getByText("Revoked", { exact: true })).toBeVisible();
        await expect(record.getByRole("button", { name: "Revoke", exact: true })).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
          device.viewport.width,
        );
      } finally {
        release?.();
        if (id) expect((await page.request.delete(`/api/api-keys/${id}`)).ok()).toBe(true);
        if (client) await client.dispose();
      }
    });
  });
}
