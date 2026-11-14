import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, submitDialog } from "./helpers";
import type { Page } from "@playwright/test";
import { join } from "node:path";
import { readFile } from "node:fs/promises";

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

test("phone project creation preserves refusal and leads to stored instructions and files", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const name = `Mobile workspace ${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    await page.goto("/projects");
    await page.getByRole("button", { name: "New project", exact: true }).first().click();
    const form = page.getByRole("dialog");
    await form.getByLabel("Name", { exact: true }).fill(name);
    await form.getByLabel("Description", { exact: true }).fill("Review customer policy questions.");
    await form.getByLabel("Instructions", { exact: true }).fill("Always include the next action.");
    await form.getByRole("button", { name: "Cancel", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "You have unsaved changes", exact: true });
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    await expect(form.getByLabel("Instructions", { exact: true })).toHaveValue(
      "Always include the next action.",
    );
    const held = await pausedRefusal(page, "/api/projects");
    release = held.release;
    await form.getByRole("button", { name: "Create", exact: true }).click();
    await held.started;
    await expect(form.getByLabel("Name", { exact: true })).toBeDisabled();
    await expect(form.getByLabel("Instructions", { exact: true })).toBeDisabled();
    await expect(form.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(form).toBeVisible();
    await form.getByLabel("Name", { exact: true }).scrollIntoViewIfNeeded();
    await photo(page, "project-create-mobile-after.png");
    held.release();
    await expect(form.getByLabel("Name", { exact: true })).toBeEnabled();
    await expect(form.getByLabel("Name", { exact: true })).toHaveValue(name);
    await held.remove();
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Create", exact: true }),
      path: "/api/projects",
    });
    const project = await nowMatching(
      page.request,
      "/api/projects",
      (row) => row.name === name,
      name,
    );
    id = String(project.id);
    await expect(page).toHaveURL(new RegExp(`/projects/${id}$`));
    await page.getByRole("tab", { name: "Files", exact: true }).click();
    const uploaded = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/projects/${id}/files`,
    );
    await page
      .locator('input[type="file"]')
      .first()
      .setInputFiles({
        name: "brief.md",
        mimeType: "text/markdown",
        buffer: Buffer.from("# Policy review\nKeep the next action explicit.\n"),
      });
    expect((await uploaded).ok()).toBe(true);
    await page.reload();
    await expect(page.getByRole("main").getByText("brief.md", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Instructions", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Instructions", exact: true })).toHaveValue(
      "Always include the next action.",
    );
  } finally {
    release?.();
    if (id) expect((await page.request.delete(`/api/projects/${id}`)).ok()).toBe(true);
  }
});

test("phone context creation preserves its source, then saves and reopens an edit", async ({
  page,
}) => {
  const name = `mobile-policy-${Date.now().toString(36)}`;
  let id: string | undefined;
  let release: (() => void) | undefined;
  try {
    await page.goto("/context");
    await page.getByRole("button", { name: "New context file", exact: true }).first().click();
    const form = page.getByRole("dialog");
    await form.getByLabel("Name", { exact: true }).fill(name);
    const details = form.getByRole("button", { name: "Details · Everyone", exact: true });
    await expect(details).toHaveAttribute("aria-expanded", "false");
    await expect(form.getByLabel("Description", { exact: true })).toBeHidden();
    await details.click();
    await form.getByLabel("Description", { exact: true }).fill("Return policy instructions.");
    await details.click();
    const source = form.getByRole("textbox", { name: /source$/ });
    await source.fill("Returns are accepted within 30 days.");
    await form.getByRole("button", { name: "Cancel", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "You have unsaved changes", exact: true });
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    const held = await pausedRefusal(page, "/api/context");
    release = held.release;
    await form.getByRole("button", { name: "Create", exact: true }).click();
    await held.started;
    await expect(source).toHaveAttribute("readonly", "");
    await expect(form.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(form).toBeVisible();
    await form.getByLabel("Name", { exact: true }).scrollIntoViewIfNeeded();
    await photo(page, "context-create-mobile-after.png");
    held.release();
    await expect(form.getByLabel("Name", { exact: true })).toBeEnabled();
    await expect(source).toHaveValue("Returns are accepted within 30 days.");
    await held.remove();
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Create", exact: true }),
      path: "/api/context",
    });
    const file = await nowMatching(page.request, "/api/context", (row) => row.name === name, name);
    id = String(file.id);
    await page.reload();
    await page
      .getByRole("button", { name: new RegExp(name) })
      .first()
      .click();
    const editor = page.getByRole("dialog", { name, exact: true });
    const body = editor.getByRole("textbox", { name: `${name}.md source`, exact: true });
    await expect(body).toHaveValue("Returns are accepted within 30 days.");
    await body.fill("Returns are accepted within 30 days. Include the next action.");
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" && response.url().endsWith(`/api/context/${id}`),
    );
    await guard.getByRole("button", { name: "Save", exact: true }).click();
    expect((await saved).ok()).toBe(true);
    await expect(editor).toBeHidden();
    await page.reload();
    await page
      .getByRole("button", { name: new RegExp(name) })
      .first()
      .click();
    await expect(body).toHaveValue("Returns are accepted within 30 days. Include the next action.");
    await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  } finally {
    release?.();
    if (id) expect((await page.request.delete(`/api/context/${id}`)).ok()).toBe(true);
  }
});

test("phone dataset creation reaches settings, versioned cases and a real CSV download", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const name = `Mobile review ${Date.now().toString(36)}`;
  let id: string | undefined;
  const releases: (() => void)[] = [];
  try {
    await page.goto("/datasets");
    await page.getByRole("button", { name: "New dataset", exact: true }).first().click();
    let form = page.getByRole("dialog");
    await form.getByRole("textbox", { name: /^Name/ }).fill(name);
    await form.getByRole("button", { name: "Cancel", exact: true }).click();
    await page
      .getByRole("dialog", { name: "You have unsaved changes", exact: true })
      .getByRole("button", { name: "Stay", exact: true })
      .click();
    let held = await pausedRefusal(page, "/api/datasets");
    releases.push(held.release);
    await form.getByRole("button", { name: "Create", exact: true }).click();
    await held.started;
    await expect(form.getByRole("textbox", { name: /^Name/ })).toBeDisabled();
    await expect(form.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(form).toBeVisible();
    await photo(page, "dataset-create-mobile-after.png");
    held.release();
    await expect(form.getByRole("textbox", { name: /^Name/ })).toBeEnabled();
    await held.remove();
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Create", exact: true }),
      path: "/api/datasets",
    });
    const dataset = await nowMatching(
      page.request,
      "/api/datasets",
      (row) => row.name === name,
      name,
    );
    id = String(dataset.id);
    await expect(page).toHaveURL(new RegExp(`/datasets/${id}$`));
    if (process.env.UI_AUDIT_SHOTS)
      await page.getByText(`Created ${name}`, { exact: true }).waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "More actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Edit details", exact: true }).click();
    form = page.getByRole("dialog");
    await form.getByLabel("Description", { exact: true }).fill("Reviewed on a phone.");
    await form.getByRole("spinbutton").fill("40");
    await page.setViewportSize({ width: 320, height: 568 });
    await expect
      .poll(async () => {
        const bounds = await form.getByRole("button", { name: "Save", exact: true }).boundingBox();
        return bounds === null ? Infinity : bounds.y + bounds.height;
      })
      .toBeLessThanOrEqual(568);
    await page.setViewportSize({ width: 320, height: 740 });
    held = await pausedRefusal(page, `/api/datasets/${id}`, "PATCH");
    releases.push(held.release);
    await form.getByRole("button", { name: "Save", exact: true }).click();
    await held.started;
    await expect(form.getByRole("spinbutton")).toBeDisabled();
    await expect(form.getByLabel("Description", { exact: true })).toBeDisabled();
    await form.getByRole("textbox", { name: /^Name/ }).scrollIntoViewIfNeeded();
    await photo(page, "dataset-edit-mobile-after.png");
    held.release();
    await expect(form.getByRole("spinbutton")).toBeEnabled();
    await expect(form.getByRole("spinbutton")).toHaveValue("40");
    await held.remove();
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Save", exact: true }),
      path: `/api/datasets/${id}`,
      method: "PATCH",
    });
    await page.reload();
    const details = await page.request.get(`/api/datasets/${id}`);
    expect(details.ok()).toBe(true);
    const reread: { description: string; improvement_holdout_share: string } = await details.json();
    expect(reread.description).toBe("Reviewed on a phone.");
    expect(Number(reread.improvement_holdout_share)).toBe(0.4);
    await page
      .getByRole("tabpanel", { name: "Cases", exact: true })
      .getByRole("button", { name: "Add case", exact: true })
      .click();
    form = page.getByRole("dialog");
    await form
      .getByRole("textbox", { name: /^User message/ })
      .fill("How long is the return window?");
    await form.getByRole("textbox", { name: "Reference answer", exact: true }).fill("30 days.");
    held = await pausedRefusal(page, `/api/datasets/${id}/cases`);
    releases.push(held.release);
    const saveCase = form.getByRole("button", { name: "Save case", exact: true });
    const beforeSaveBounds = await saveCase.boundingBox();
    await saveCase.click();
    await held.started;
    await expect
      .poll(async () => {
        const bounds = await saveCase.boundingBox();
        return bounds === null || beforeSaveBounds === null
          ? Infinity
          : Math.abs(bounds.width - beforeSaveBounds.width);
      })
      .toBeLessThanOrEqual(1);
    await expect(form.getByRole("textbox", { name: /^User message/ })).toBeDisabled();
    await expect(form.getByRole("button", { name: "Edit as JSON", exact: true })).toBeDisabled();
    await expect(form.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(form).toBeVisible();
    await form.getByRole("textbox", { name: /^User message/ }).scrollIntoViewIfNeeded();
    await photo(page, "dataset-case-mobile-after.png");
    held.release();
    await expect(form.getByRole("textbox", { name: /^User message/ })).toBeEnabled();
    await held.remove();
    await expect(form.getByRole("textbox", { name: "Reference answer", exact: true })).toHaveValue(
      "30 days.",
    );
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Save case", exact: true }),
      path: `/api/datasets/${id}/cases`,
    });
    await nowMatching(
      page.request,
      `/api/datasets/${id}/cases`,
      (row) => row.input === "How long is the return window?",
      "stored question",
    );
    await page.reload();
    await expect(
      page.getByRole("main").getByText("How long is the return window?", { exact: true }).first(),
    ).toBeVisible();
    await page.getByRole("button", { name: "More actions", exact: true }).click();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("menuitem", { name: "Export CSV", exact: true }).click();
    const download = await downloaded;
    const path = await download.path();
    expect(path).not.toBeNull();
    const csv = await readFile(path!, "utf8");
    expect(csv).toContain("How long is the return window?");
    expect(csv).toContain("30 days.");
  } finally {
    for (const release of releases) release();
    if (id) expect((await page.request.delete(`/api/datasets/${id}`)).ok()).toBe(true);
  }
});

test("phone dropped context files remain queued after Stay and save in order", async ({ page }) => {
  const suffix = Date.now().toString(36);
  const names: readonly [string, string] = [`first-policy-${suffix}`, `second-policy-${suffix}`];
  const ids: string[] = [];
  try {
    await page.goto("/context");
    await expect(
      page.getByRole("button", { name: "New context file", exact: true }).first(),
    ).toBeVisible();
    await page.evaluate((files) => {
      const transfer = new DataTransfer();
      for (const [index, name] of files.entries())
        transfer.items.add(
          new File([`Policy ${index + 1}.`], `${name}.md`, { type: "text/markdown" }),
        );
      window.dispatchEvent(
        new DragEvent("drop", { dataTransfer: transfer, bubbles: true, cancelable: true }),
      );
    }, names);
    let form = page.getByRole("dialog");
    await expect(form.getByLabel("Name", { exact: true })).toHaveValue(names[0]);
    await form.getByRole("button", { name: "Cancel", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "You have unsaved changes", exact: true });
    await expect(guard.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    // The first save advances the queue rather than closing the dialog.
    const created = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.status() !== 401 &&
        response.url().endsWith("/api/context"),
    );
    await form.getByRole("button", { name: "Create", exact: true }).click();
    expect((await created).ok()).toBe(true);
    const first = await nowMatching(
      page.request,
      "/api/context",
      (row) => row.name === names[0],
      names[0],
    );
    ids.push(String(first.id));
    form = page.getByRole("dialog");
    await expect(form.getByLabel("Name", { exact: true })).toHaveValue(names[1]);
    await expect(form.getByRole("textbox", { name: /source$/ })).toHaveValue("Policy 2.");
    await submitDialog(page, {
      dialog: form,
      submit: form.getByRole("button", { name: "Create", exact: true }),
      path: "/api/context",
    });
    const second = await nowMatching(
      page.request,
      "/api/context",
      (row) => row.name === names[1],
      names[1],
    );
    ids.push(String(second.id));
    await page.reload();
    for (const name of names)
      await expect(page.getByRole("button", { name: new RegExp(name) }).first()).toBeVisible();
  } finally {
    for (const id of ids) expect((await page.request.delete(`/api/context/${id}`)).ok()).toBe(true);
  }
});
