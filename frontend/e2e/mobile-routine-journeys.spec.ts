import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, rowsAt, submitDialog } from "./helpers";
import type { APIResponse, Page } from "@playwright/test";

test.use({
  storageState: AUTH_STATE,
  actionTimeout: 15_000,
  viewport: { width: 320, height: 568 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

async function publishedAgent(page: Page): Promise<{ id: string; name: string }> {
  const row = (await rowsAt(page.request, "/api/agents")).find(
    (agent) =>
      typeof agent.current_version_id === "string" &&
      agent.can_run === true &&
      agent.kind === "agent",
  );
  if (!row || typeof row.id !== "string" || typeof row.name !== "string")
    throw new Error("A seeded published runnable agent is required");
  return { id: row.id, name: row.name };
}
async function createdId(response: Pick<APIResponse, "ok" | "status" | "json">): Promise<string> {
  expect(response.ok(), `write answered ${response.status()}`).toBe(true);
  const row: unknown = await response.json();
  if (typeof row !== "object" || row === null || !("id" in row) || typeof row.id !== "string")
    throw new Error("Missing created id");
  return row.id;
}
async function refuseLater(page: Page, path: string, method: "POST" | "PATCH") {
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
    await route.fulfill({ status: 403, json: { detail: "Controlled routine save refusal" } });
  });
  return { started, release, remove: () => page.unroute(pattern) };
}

test("phone schedule search, refusal, edit, reload and deletion keep the action footer reachable", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const agent = await publishedAgent(page);
  const name = `Weekly customer follow-up ${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    id = await createdId(
      await page.request.post(`/api/agents/${agent.id}/triggers`, {
        data: {
          name,
          prompt: "Review customer questions and prepare the next actions.",
          trigger_type: "schedule",
          schedule_kind: "cron",
          cron_expression: "0 9 * * 1",
          time_zone: "Europe/Warsaw",
          is_active: false,
          runs_as_creator: true,
        },
      }),
    );
    const path = `/api/agents/${agent.id}/triggers/${id}`;
    await page.goto("/routines");
    await page.getByPlaceholder("Search routines").fill(name);
    const row = page.getByRole("listitem").filter({ hasText: name });
    await expect(row).toBeVisible();
    await page.getByPlaceholder("Search routines").fill("nothing-matches-ui-review");
    await expect(page.getByText("No routine matches that.", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Clear search", exact: true })
      .filter({ hasText: "Clear search" })
      .click();
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Edit", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^Name/).fill(`${name} updated`);
    await dialog
      .getByRole("textbox", { name: "Message", exact: true })
      .fill("Include the customer, blocker and next owner for every open question.");
    const held = await refuseLater(page, path, "PATCH");
    release = held.release;
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await held.started;
    await expect(dialog.getByLabel(/^Name/)).toBeDisabled();
    await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toBeDisabled();
    for (const label of ["Cancel", "Close", "Run now"])
      await expect(dialog.getByRole("button", { name: label, exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    const button = await dialog.getByRole("button", { name: "Save", exact: true }).boundingBox();
    expect(button).not.toBeNull();
    if (button) expect(button.y + button.height).toBeLessThanOrEqual(568);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      320,
    );
    held.release();
    await expect(dialog.getByLabel(/^Name/)).toBeEnabled();
    await held.remove();
    await expect(dialog.getByLabel(/^Name/)).toHaveValue(`${name} updated`);
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Save", exact: true }),
      path,
      method: "PATCH",
    });
    const saved = await nowMatching(
      page.request,
      `/api/agents/${agent.id}/triggers`,
      (entry) => entry.id === id && entry.name === `${name} updated`,
      "updated paused schedule",
    );
    expect(saved.is_active).toBe(false);
    await page.reload();
    await page.getByPlaceholder("Search routines").fill(`${name} updated`);
    await row.getByRole("button", { name: "Edit", exact: true }).click();
    await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(
      "Include the customer, blocker and next owner for every open question.",
    );
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await row.getByRole("button", { name: "Delete", exact: true }).click();
    await submitDialog(page, {
      dialog: page.getByRole("dialog"),
      submit: page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }),
      path,
      method: "DELETE",
    });
    id = undefined;
    await expect(row).toHaveCount(0);
  } finally {
    release?.();
    if (id)
      expect((await page.request.delete(`/api/agents/${agent.id}/triggers/${id}`)).ok()).toBe(true);
  }
});

test("phone event wizard preserves back navigation and a refused draft before creating an unfired webhook", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const agent = await publishedAgent(page);
  const name = `Incoming customer note ${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    await page.goto("/routines");
    await page.getByRole("button", { name: "New routine", exact: true }).click();
    await page.getByRole("menuitem", { name: "Run when an event arrives", exact: true }).click();
    await page
      .getByRole("group", { name: "API trigger", exact: true })
      .getByRole("button", { name: "Create trigger", exact: true })
      .click();
    const dialog = page.getByRole("dialog").last();
    await dialog
      .getByLabel("Signing secret", { exact: true })
      .fill("ui-audit-demo-signing-key-only");
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    await dialog.getByRole("combobox", { name: "Agent", exact: true }).click();
    await page.getByRole("option", { name: agent.name, exact: true }).click();
    await dialog.getByLabel(/^Name/).fill(name);
    await dialog.locator('[data-tour="routine-advanced"]').click();
    await dialog.getByRole("checkbox", { name: /^Run as me/ }).check();
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    await dialog
      .getByRole("textbox", { name: "Message", exact: true })
      .fill("Review the incoming note and prepare the next action.");
    await dialog.getByRole("button", { name: "Back", exact: true }).click();
    await expect(dialog.getByLabel(/^Name/)).toHaveValue(name);
    await dialog.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(
      "Review the incoming note and prepare the next action.",
    );
    const path = `/api/agents/${agent.id}/triggers`;
    const held = await refuseLater(page, path, "POST");
    release = held.release;
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await held.started;
    await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Back", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    held.release();
    await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    await held.remove();
    const accepted = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === path &&
        response.request().method() === "POST" &&
        response.ok(),
    );
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    id = await createdId(await accepted);
    const summary = page.getByRole("dialog", { name: "One more step", exact: true });
    await expect(summary).toBeVisible();
    await expect(summary.getByLabel("Webhook URL", { exact: true })).toHaveValue(
      /webhooks\/triggers\//,
    );
    const stored = await nowMatching(page.request, path, (entry) => entry.id === id, name);
    expect(stored.last_run_id).toBeNull();
    expect(JSON.stringify(stored)).not.toContain("ui-audit-demo-signing-key-only");
    await summary.getByRole("button", { name: "Done", exact: true }).click();
    await page.keyboard.press("Escape");
    await page.getByPlaceholder("Search routines").fill(name);
    await expect(page.getByRole("listitem").filter({ hasText: name })).toBeVisible();
    await page.reload();
    await page.getByPlaceholder("Search routines").fill(name);
    await expect(page.getByRole("listitem").filter({ hasText: name })).toBeVisible();
  } finally {
    release?.();
    if (id)
      expect((await page.request.delete(`/api/agents/${agent.id}/triggers/${id}`)).ok()).toBe(true);
  }
});
