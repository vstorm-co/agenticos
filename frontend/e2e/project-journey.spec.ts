import { expect, test } from "./fixtures";
import { AUTH_STATE, nowListed, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE });

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`project edits survive the journey from instructions to files at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/projects");
    await page.getByRole("button", { name: "New project", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    const name = `Project journey ${viewport.width} ${Date.now().toString(36)}`;
    await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(name);
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Create", exact: true }),
      path: "/api/projects",
    });
    await nowListed(page.request, "/api/projects", "name", name);
    await expect(page).toHaveURL(/\/projects\/[^/?]+$/);
    const projectPath = new URL(page.url()).pathname;
    await page.getByRole("tab", { name: "Instructions", exact: true }).click();
    const instructions = page.getByRole("textbox", { name: "Instructions", exact: true });
    const draft = "Finish every answer with a clear next step.";
    await instructions.fill(draft);
    await page.getByRole("tab", { name: "Files", exact: true }).click();
    const guard = page.getByRole("dialog", { name: "You have unsaved changes" });
    await expect(guard).toBeVisible();
    await guard.getByRole("button", { name: "Stay", exact: true }).click();
    await expect(instructions).toHaveValue(draft);

    // A refused write must leave both the user and the draft where they were.
    const updatePath = `**/api${projectPath}`;
    await page.route(updatePath, (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({ status: 409, json: { detail: "Project was changed elsewhere" } })
        : route.continue(),
    );
    await page.getByRole("tab", { name: "Files", exact: true }).click();
    await guard.getByRole("button", { name: "Save", exact: true }).click();
    await expect(guard).toBeHidden();
    await expect(instructions).toHaveValue(draft);
    await expect(page.getByRole("tab", { name: "Instructions", exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.unroute(updatePath);

    await page.getByRole("tab", { name: "Files", exact: true }).click();
    await guard.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("tab", { name: "Files", exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect
      .poll(async () => {
        const response = await page.request.get(`/api${projectPath}`);
        expect(response.ok()).toBe(true);
        return (await response.json()).instructions;
      })
      .toBe(draft);

    const uploaded = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api${projectPath}/files` &&
        response.request().method() === "POST" &&
        response.status() !== 401,
    );
    await page
      .locator('input[type="file"]')
      .first()
      .setInputFiles({
        name: "brief.md",
        mimeType: "text/markdown",
        buffer: Buffer.from("# Project brief\nKeep the next step explicit.\n"),
      });
    expect((await uploaded).ok()).toBe(true);
    await expect(page.getByRole("main").getByText("brief.md", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("main").getByText("brief.md", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Instructions", exact: true }).click();
    await expect(instructions).toHaveValue(draft);

    await instructions.fill("This change is deliberately discarded.");
    await page.getByRole("tab", { name: "Chats", exact: true }).click();
    await guard.getByRole("button", { name: "Discard", exact: true }).click();
    await page.getByRole("tab", { name: "Instructions", exact: true }).click();
    await expect(instructions).toHaveValue(draft);
    await expect(page.locator("main")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect((await page.request.delete(`/api${projectPath}`)).ok()).toBe(true);
  });
}
