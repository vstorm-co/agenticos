import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

/** The organization the console acts in, as it stored the choice. */
async function activeOrganization(page: Page): Promise<string> {
  const read = () =>
    page.evaluate(() => {
      const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
      if (typeof value !== "object" || value === null || !("state" in value)) return null;
      const state = value.state;
      return typeof state === "object" &&
        state !== null &&
        "activeOrgId" in state &&
        typeof state.activeOrgId === "string"
        ? state.activeOrgId
        : null;
    });
  await expect.poll(read).toBeTruthy();
  return (await read()) ?? "";
}

test("an edit left without saving asks first, and comes back when the page is opened again", async ({
  page,
}) => {
  await page.goto("/datasets");
  const headers = { "X-Organization-Id": await activeOrganization(page) };
  const stamp = Date.now().toString(36);
  const created = await page.request.post("/api/datasets", {
    headers,
    data: { name: `Unsaved changes ${stamp}` },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = (await created.json()) as { id: string };
  const added = await page.request.post(`/api/datasets/${id}/cases`, {
    headers,
    data: { input: "How long is the return window?", checks: [{ type: "contains", value: "30" }] },
  });
  expect(added.ok(), await added.text()).toBeTruthy();

  await page.goto(`/datasets/${id}`);
  await page.getByRole("button", { name: /How long is the return window\?/ }).click();
  const editor = page.getByRole("dialog", { name: "Case" });
  await editor.getByRole("button", { name: "Edit", exact: true }).click();
  const input = editor.getByLabel(/^Input/);
  await input.fill("How long is the return window for shoes?");

  // Closing the editor asks first; Stay keeps the edit where it is.
  await page.keyboard.press("Escape");
  const asked = page.getByRole("dialog", { name: "You have unsaved changes" });
  await expect(asked).toBeVisible();
  await asked.getByRole("button", { name: "Stay" }).click();
  await expect(asked).toBeHidden();
  await expect(input).toHaveValue("How long is the return window for shoes?");

  // Leaving the page without deciding: the browser asks, and the edit is kept here.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.goto("/datasets");
  await page.goto(`/datasets/${id}`);

  const offer = page.getByRole("region", { name: "Restore your unsaved changes?" });
  await expect(offer).toBeVisible();
  await offer.getByRole("button", { name: "Restore" }).click();
  await expect(offer).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Case" }).getByLabel(/^Input/)).toHaveValue(
    "How long is the return window for shoes?",
  );
});
