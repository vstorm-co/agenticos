import { expect, test } from "./fixtures";
import { AUTH_STATE, nowListed, nowMatching, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("context editing keeps changes through close, failed save and reopen", async ({ page }) => {
  const name = `context-journey-${Date.now().toString(36)}`;
  await page.goto("/context");
  await page.getByRole("button", { name: "New context file", exact: true }).first().click();
  const create = page.getByRole("dialog");
  await create.getByLabel("Name", { exact: true }).fill(name);
  await create.locator("textarea").fill("Original policy.");
  await submitDialog(page, {
    dialog: create,
    submit: create.getByRole("button", { name: "Create", exact: true }),
    path: "/api/context",
  });
  const row = await nowMatching(page.request, "/api/context", (item) => item.name === name, name);
  await page
    .getByRole("button", { name: new RegExp(name) })
    .first()
    .click();
  const editor = page.getByRole("dialog", { name, exact: true });
  const content = page.getByRole("textbox", { name: `${name}.md source`, exact: true });
  await content.fill("Original policy. Include the next step.");
  await page.keyboard.press("Escape");
  const guard = page.getByRole("dialog", { name: "You have unsaved changes" });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(content).toHaveValue("Original policy. Include the next step.");
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await guard.getByRole("button", { name: "Discard", exact: true }).click();
  await expect(editor).toBeHidden();
  await page
    .getByRole("button", { name: new RegExp(name) })
    .first()
    .click();
  await expect(content).toHaveValue("Original policy.");
  await content.fill("Saved policy with the next step.");
  await page.route("**/api/context/*", (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({ status: 409, json: { detail: "Context changed elsewhere" } })
      : route.continue(),
  );
  await page.keyboard.press("Escape");
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(guard).toBeHidden();
  await expect(content).toHaveValue("Saved policy with the next step.");
  await page.unroute("**/api/context/*");
  await page.keyboard.press("Escape");
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(editor).toBeHidden();
  await page.reload();
  await page
    .getByRole("button", { name: new RegExp(name) })
    .first()
    .click();
  await expect(content).toHaveValue("Saved policy with the next step.");
  expect((await page.request.delete(`/api/context/${String(row.id)}`)).ok()).toBe(true);
});

test("a skill resource keeps a refused edit and saves before switching files", async ({ page }) => {
  const name = `skill-journey-${Date.now().toString(36)}`;
  await page.goto("/skills");
  await page.getByRole("button", { name: "New skill", exact: true }).first().click();
  const create = page.getByRole("dialog");
  await create.getByLabel("Name", { exact: true }).fill(name);
  await create.getByLabel("Description", { exact: true }).fill("Review changes before publishing.");
  await create
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: "checklist.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Review\nCheck instructions."),
    });
  await submitDialog(page, {
    dialog: create,
    submit: create.getByRole("button", { name: "Create", exact: true }),
    path: "/api/skills",
  });
  await nowListed(page.request, "/api/skills", "name", name);
  const skill = await nowMatching(page.request, "/api/skills", (item) => item.name === name, name);
  await page
    .getByRole("button", { name: new RegExp(name) })
    .first()
    .click();
  const editor = page.getByRole("dialog", { name, exact: true });
  const bodyDraft = "Keep the review instructions with the saved checklist.";
  await editor.getByRole("textbox", { name: "Instructions source", exact: true }).fill(bodyDraft);
  await editor.getByRole("treeitem", { name: "checklist.md", exact: true }).click();
  const input = editor.getByRole("textbox", { name: "checklist.md source", exact: true });
  const draft = "# Review\nCheck instructions.\nKeep this next step.";
  await input.fill(draft);
  await page.route("**/api/skills/*/resources/*", (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({ status: 409, json: { detail: "File changed elsewhere" } })
      : route.continue(),
  );
  await editor.getByRole("button", { name: "Save file", exact: true }).click();
  await expect(input).toHaveValue(draft);
  // The resource must fail before the body save can close the workbench.
  await page.keyboard.press("Escape");
  const guard = page.getByRole("dialog", { name: "You have unsaved changes" });
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(guard).toBeHidden();
  await expect(input).toHaveValue(draft);
  await editor.getByRole("button", { name: "Instructions", exact: true }).click();
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(guard).toBeHidden();
  await expect(input).toHaveValue(draft);
  await page.unroute("**/api/skills/*/resources/*");
  await page.keyboard.press("Escape");
  await guard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(input).toHaveValue(draft);
  await editor.getByRole("button", { name: "Instructions", exact: true }).click();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    editor.getByRole("textbox", { name: "Instructions source", exact: true }),
  ).toHaveValue(bodyDraft);
  await editor.getByRole("treeitem", { name: "checklist.md", exact: true }).click();
  await expect(input).toHaveValue(draft);
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await guard.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Save now", exact: true }).click();
  await expect(editor).toBeHidden();
  await page.reload();
  await page
    .getByRole("button", { name: new RegExp(name) })
    .first()
    .click();
  await expect(
    editor.getByRole("textbox", { name: "Instructions source", exact: true }),
  ).toHaveValue(bodyDraft);
  await editor.getByRole("treeitem", { name: "checklist.md", exact: true }).click();
  await expect(input).toHaveValue(draft);
  expect((await page.request.delete(`/api/skills/${String(skill.id)}`)).ok()).toBe(true);
});
