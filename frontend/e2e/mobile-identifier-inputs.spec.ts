import { test, expect } from "./fixtures";
import { AUTH_STATE, nowMatching, submitDialog } from "./helpers";
import { join } from "node:path";

test.use({
  storageState: AUTH_STATE,
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});

test("phone skill names normalize, persist and preserve the draft on collision", async ({
  page,
}) => {
  const suffix = Date.now().toString(36);
  const title = `Strategic Diagnostic ${suffix}`;
  const name = `strategic-diagnostic-${suffix}`;
  const ids: string[] = [];
  try {
    await page.goto("/skills");
    await page.getByRole("button", { name: "New skill", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name", { exact: true }).fill(title);
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(title);
    await dialog
      .getByLabel("Description", { exact: true })
      .fill("A repeatable strategic diagnostic.");
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(name);
    await expect(dialog.getByLabel("Name", { exact: true })).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
    await dialog.getByLabel("Name", { exact: true }).scrollIntoViewIfNeeded();
    if (process.env.UI_AUDIT_SHOTS) {
      await dialog.getByLabel("Name", { exact: true }).fill("Strategic Diagnostic");
      await dialog.getByLabel("Description", { exact: true }).focus();
      await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue("strategic-diagnostic");
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "skill-name-mobile-after.png"),
      });
      await dialog.getByLabel("Name", { exact: true }).fill(title);
    }
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Create", exact: true }),
      path: "/api/skills",
    });
    const skill = await nowMatching(page.request, "/api/skills", (row) => row.name === name, name);
    ids.push(String(skill.id));
    await page.reload();
    await expect(page.getByRole("button", { name: new RegExp(name) }).first()).toBeVisible();
    await page.getByRole("button", { name: "New skill", exact: true }).click();
    await dialog.getByLabel("Name", { exact: true }).fill(title);
    await dialog
      .getByLabel("Description", { exact: true })
      .fill("Keep this draft after a name collision.");
    const refused = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/skills") && response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    expect((await refused).status()).toBe(409);
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    await expect(dialog.getByLabel("Description", { exact: true })).toHaveValue(
      "Keep this draft after a name collision.",
    );
    await dialog.getByLabel("Name", { exact: true }).fill(`Revised Diagnostic ${suffix}`);
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Create", exact: true }),
      path: "/api/skills",
    });
    const revised = await nowMatching(
      page.request,
      "/api/skills",
      (row) => row.name === `revised-diagnostic-${suffix}`,
      "revised skill",
    );
    ids.push(String(revised.id));
  } finally {
    for (const id of ids) expect((await page.request.delete(`/api/skills/${id}`)).ok()).toBe(true);
  }
});

test("phone custom commands accept pasted names and survive re-entry", async ({ page }) => {
  const suffix = Date.now().toString(36);
  const name = `daily-review-${suffix}`;
  let id: string | undefined;
  try {
    await page.goto("/settings/slash-commands");
    await page.getByRole("button", { name: "New command", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name", { exact: true }).fill(`/Daily Review ${suffix}`);
    await dialog.getByLabel("Prompt", { exact: true }).fill("Summarize the decisions from today.");
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(name);
    if (process.env.UI_AUDIT_SHOTS)
      await page.screenshot({
        path: join(process.env.UI_AUDIT_SHOTS, "command-name-mobile-after.png"),
      });
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Create", exact: true }),
      path: "/api/me/slash-commands",
    });
    const command = await nowMatching(
      page.request,
      "/api/me/slash-commands",
      (row) => row.name === name,
      name,
    );
    id = String(command.id);
    await page.reload();
    await expect(page.getByRole("main").getByText(`/${name}`, { exact: true })).toBeVisible();
  } finally {
    if (id) expect((await page.request.delete(`/api/me/slash-commands/${id}`)).ok()).toBe(true);
  }
});
