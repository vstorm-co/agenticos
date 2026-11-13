import { expect, test } from "./fixtures";
import { AUTH_STATE, nowListed, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE, hasTouch: true });

test("a workflow publishes, returns output and keeps run controls reachable on a phone", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const name = `Workflow journey ${Date.now().toString(36)}`;
  const answer = "The workflow is ready for review.";
  await page.goto("/workflows");
  await page.getByRole("button", { name: "New workflow", exact: true }).first().click();
  const create = page.getByRole("dialog");
  await create.getByRole("textbox", { name: /^Name/ }).fill(name);
  await submitDialog(page, {
    dialog: create,
    submit: create.getByRole("button", { name: "Create", exact: true }),
    path: "/api/workflows",
  });
  await nowListed(page.request, "/api/workflows", "name", name);
  await expect(page).toHaveURL(/\/workflows\/[^/?]+$/);
  const workflowPath = new URL(page.url()).pathname;
  await page.getByRole("button", { name: "Add a step after Manual (Out)", exact: true }).click();
  await page.getByRole("option", { name: /^Finish/ }).click();
  await page.getByRole("option", { name: /^Output/ }).click();
  const step = page.getByRole("dialog", { name: "Output", exact: true });
  await step.getByLabel("Text", { exact: true }).fill(answer);
  await step.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  const publish = page.getByRole("dialog");
  const published = page.waitForResponse(
    (response) => new URL(response.url()).pathname === `/api${workflowPath}/publish`,
  );
  await publish.getByRole("button", { name: "Publish version", exact: true }).click();
  expect((await published).ok()).toBe(true);
  await expect(publish).toBeHidden();
  await page.reload();
  await expect(page.getByRole("main")).toContainText("Live · version 1");

  await page.setViewportSize({ width: 320, height: 740 });
  const started = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/workflow-runs" &&
      response.request().method() === "POST" &&
      response.status() !== 401,
  );
  await page.getByRole("button", { name: "Test draft", exact: true }).click();
  const response = await started;
  expect(response.ok()).toBe(true);
  const run: { id: string } = await response.json();
  await expect
    .poll(
      async () => {
        const read = await page.request.get(`/api/workflow-runs/${run.id}`);
        expect(read.ok()).toBe(true);
        return (await read.json()).status;
      },
      { timeout: 30_000 },
    )
    .toBe("succeeded");
  const saved = await page.request.get(`/api/workflow-runs/${run.id}`);
  expect((await saved.json()).output.text).toBe(answer);
  const bar = page.getByRole("status").filter({ hasText: "Test run" });
  await expect(bar).toContainText("Succeeded");
  await expect(bar).toContainText("2 steps done");
  for (const control of [
    bar,
    bar.getByRole("link", { name: "Open run" }),
    bar.getByRole("button", { name: "Hide the run" }),
  ]) {
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
  }
  await bar.getByRole("link", { name: "Open run", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${workflowPath}/runs/${run.id}$`));
  await page.getByRole("tab", { name: "Output", exact: true }).click();
  await expect(page.getByRole("main")).toContainText(answer);
  await page.reload();
  await page.getByRole("tab", { name: "Output", exact: true }).click();
  await expect(page.getByRole("main")).toContainText(answer);
  expect((await page.request.delete(`/api${workflowPath}`)).ok()).toBe(true);
});
