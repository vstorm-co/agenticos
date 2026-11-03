import { expect, test } from "./fixtures";
import { AUTH_STATE, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("pipeline models and instructions belong to the dataset", async ({ page }) => {
  await page.goto("/agents");
  await expect(page.getByText("System agents", { exact: true })).toHaveCount(0);
  await page.goto("/datasets");
  await page.getByRole("button", { name: "New dataset", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: /^Name/ }).fill(`Pipeline settings ${Date.now()}`);
  await submitDialog(page, {
    dialog,
    submit: dialog.getByRole("button", { name: "Create", exact: true }),
    method: "POST",
    path: "/api/datasets",
  });
  await page.waitForURL(/\/datasets\/[^/?]+$/);
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  const generator = page.locator('[data-tour="datasets-generator-settings"]');
  await generator
    .locator("summary")
    .filter({ hasText: /Use a saved model/ })
    .click();
  const model = generator.locator('[role="radio"]:not([disabled])').first();
  await expect(model).toBeEnabled();
  await model.click();
  const instructions =
    "Generate cases from the published refund policy. Include a clear expected answer.";
  await generator.getByRole("textbox", { name: "Instructions", exact: true }).fill(instructions);
  await generator.getByRole("button", { name: "Save", exact: true }).click();
  await expect(generator.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(generator.getByRole("textbox", { name: "Instructions", exact: true })).toHaveValue(
    instructions,
  );
  await page.getByRole("tab", { name: "Grading", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instructions", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Which judge", exact: true })).toHaveCount(0);
});
