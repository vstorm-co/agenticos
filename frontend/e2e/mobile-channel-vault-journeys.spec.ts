import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, submitDialog } from "./helpers";
import type { Page } from "@playwright/test";
import { join } from "node:path";

test.use({
  storageState: AUTH_STATE,
  viewport: { width: 320, height: 740 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

interface PausedRefusal {
  started: Promise<void>;
  release: () => void;
  remove: () => Promise<void>;
}
async function pausedRefusal(
  page: Page,
  path: string,
  method: "POST" | "PATCH" = "POST",
): Promise<PausedRefusal> {
  let release!: () => void;
  let began!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const started = new Promise<void>((resolve) => {
    began = resolve;
  });
  const pattern = `**${path}`;
  await page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.continue();
    began();
    await held;
    await route.fulfill({ status: 403, json: { detail: "Controlled mobile write refusal" } });
  });
  return { started, release, remove: () => page.unroute(pattern) };
}
async function photo(page: Page, name: string): Promise<void> {
  if (process.env.UI_AUDIT_SHOTS)
    await page.screenshot({ path: join(process.env.UI_AUDIT_SHOTS, name) });
}

async function assertSaving(page: Page, name: string): Promise<void> {
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel(/^Name/)).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel(/^Name/)).toHaveValue(name);
}

test("phone channel registration clears cancelled credentials and survives a refused create and edit", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const name = `Mobile support ${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    await page.goto("/channels");
    await page.getByRole("button", { name: "Add channel", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await photo(page, "channel-platform-mobile-after.png");
    const platform = dialog.getByRole("combobox", { name: "Platform", exact: true });
    await platform.click();
    await page.getByRole("option", { name: "Slack", exact: true }).click();
    await dialog.getByLabel(/^Name/).fill(name);
    await dialog.getByLabel(/Bot token/i).fill("ui-audit-demo-token-not-real");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "Add channel", exact: true }).first().click();
    await expect(dialog.getByLabel(/^Name/)).toHaveValue("");
    await expect(dialog.getByLabel(/Bot token/i)).toHaveValue("");
    await dialog.getByLabel(/Bot token/i).scrollIntoViewIfNeeded();
    await photo(page, "channel-cancel-mobile-after.png");
    await platform.click();
    await page.getByRole("option", { name: "Slack", exact: true }).click();
    await dialog.getByLabel(/^Name/).fill(name);
    await dialog.getByLabel(/Bot token/i).fill("ui-audit-demo-token-not-real");
    const held = await pausedRefusal(page, "/api/channels/bots");
    release = held.release;
    await dialog.getByRole("button", { name: "Register", exact: true }).click();
    await held.started;
    await assertSaving(page, name);
    await expect(platform).toBeDisabled();
    held.release();
    await expect(dialog.getByLabel(/^Name/)).toBeEnabled();
    await expect(dialog.getByLabel(/Bot token/i)).toHaveValue("ui-audit-demo-token-not-real");
    await held.remove();
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Register", exact: true }),
      path: "/api/channels/bots",
    });
    const stored = await nowMatching(
      page.request,
      "/api/channels/bots",
      (row) => row.name === name,
      name,
    );
    expect(typeof stored.id).toBe("string");
    if (typeof stored.id !== "string") throw new Error("Missing stored id");
    id = stored.id;
    expect(stored.webhook_mode).toBe(true);
    await page.reload();
    await page.getByRole("button", { name: `Edit ${name}`, exact: true }).click();
    await expect(dialog.getByLabel(/Bot token/i)).toHaveValue("");
    await dialog.getByLabel(/^Name/).fill(`${name} updated`);
    const editHeld = await pausedRefusal(page, `/api/channels/bots/${id}`, "PATCH");
    release = editHeld.release;
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await editHeld.started;
    await assertSaving(page, `${name} updated`);
    editHeld.release();
    await expect(dialog.getByLabel(/^Name/)).toBeEnabled();
    await editHeld.remove();
    await page.setViewportSize({ width: 320, height: 568 });
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Save", exact: true }),
      path: `/api/channels/bots/${id}`,
      method: "PATCH",
    });
    await nowMatching(
      page.request,
      "/api/channels/bots",
      (row) => row.id === id && row.name === `${name} updated`,
      `${name} updated`,
    );
    await page.reload();
    await page.getByRole("button", { name: `Edit ${name} updated`, exact: true }).click();
    await expect(dialog.getByLabel(/^Name/)).toHaveValue(`${name} updated`);
    await expect(dialog.getByLabel(/Bot token/i)).toHaveValue("");
  } finally {
    release?.();
    if (id) expect((await page.request.delete(`/api/channels/bots/${id}`)).ok()).toBe(true);
  }
});

test("phone vault clears cancelled values and retries store and rotation without replacing the secret", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const name = `Mobile demo credential ${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    await page.goto("/vault");
    await page.getByRole("button", { name: "Add key", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: /^Something else/ }).click();
    await dialog.getByLabel(/^Name/).fill(name);
    await dialog.getByRole("textbox", { name: /API key/i }).fill("ui-audit-demo-first-AAAA");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "Add key", exact: true }).first().click();
    await expect(dialog.getByRole("textbox", { name: /API key/i })).toHaveValue("");
    await dialog.getByRole("textbox", { name: /API key/i }).scrollIntoViewIfNeeded();
    await photo(page, "vault-cancel-mobile-after.png");
    await dialog.getByRole("button", { name: /^Something else/ }).click();
    await dialog.getByLabel(/^Name/).fill(name);
    await dialog.getByRole("textbox", { name: /API key/i }).fill("ui-audit-demo-first-AAAA");
    const held = await pausedRefusal(page, "/api/secrets");
    release = held.release;
    await dialog.getByRole("button", { name: "Store key", exact: true }).click();
    await held.started;
    await assertSaving(page, name);
    await expect(dialog.getByRole("textbox", { name: /API key/i })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: /^Something else/ })).toBeDisabled();
    held.release();
    await expect(dialog.getByLabel(/^Name/)).toBeEnabled();
    await held.remove();
    await expect(dialog.getByRole("textbox", { name: /API key/i })).toHaveValue(
      "ui-audit-demo-first-AAAA",
    );
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Store key", exact: true }),
      path: "/api/secrets",
    });
    const stored = await nowMatching(
      page.request,
      "/api/secrets",
      (row) => row.name === name,
      name,
    );
    expect(typeof stored.id).toBe("string");
    if (typeof stored.id !== "string") throw new Error("Missing stored id");
    id = stored.id;
    expect(stored.hint).toBe("AAAA");
    expect(JSON.stringify(stored)).not.toContain("ui-audit-demo-first");
    await page.reload();
    await page.getByRole("button", { name: `Rotate ${name}`, exact: true }).click();
    const key = dialog.getByRole("textbox", { name: /API key/i });
    await key.fill("ui-audit-demo-second-BBBB");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: `Rotate ${name}`, exact: true }).click();
    await expect(key).toHaveValue("");
    await page.setViewportSize({ width: 320, height: 568 });
    await photo(page, "vault-rotate-mobile-after.png");
    await key.fill("ui-audit-demo-second-BBBB");
    const rotation = await pausedRefusal(page, `/api/secrets/${id}`, "PATCH");
    release = rotation.release;
    await dialog.getByRole("button", { name: "Rotate", exact: true }).click();
    await rotation.started;
    await expect(key).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    rotation.release();
    await expect(key).toBeEnabled();
    await rotation.remove();
    await expect(key).toHaveValue("ui-audit-demo-second-BBBB");
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Rotate", exact: true }),
      path: `/api/secrets/${id}`,
      method: "PATCH",
    });
    const updated = await nowMatching(
      page.request,
      "/api/secrets",
      (row) => row.id === id && row.hint === "BBBB",
      "rotated secret",
    );
    expect(updated.id).toBe(id);
    expect(JSON.stringify(updated)).not.toContain("ui-audit-demo-second");
    await page.reload();
    await page.getByRole("button", { name: `Rotate ${name}`, exact: true }).click();
    await expect(key).toHaveValue("");
    await expect(dialog).toContainText("BBBB");
  } finally {
    release?.();
    if (id) expect((await page.request.delete(`/api/secrets/${id}`)).ok()).toBe(true);
  }
});
