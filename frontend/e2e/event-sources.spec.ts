import { randomUUID } from "node:crypto";

import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("source forms scroll their fields without moving the primary action", async ({ page }) => {
  const name = `Viewport source ${randomUUID()}`;
  const created = await page.request.post("/api/event-sources", {
    data: {
      name,
      provider: "webhook",
      auth: { method: "hmac" },
      credentials: { secret: "example-only" },
    },
  });
  expect(created.ok()).toBe(true);
  const { id } = (await created.json()) as { id: string };
  try {
    await page.goto("/event-sources");
    await expect(page.getByRole("heading", { name })).toBeVisible();
    for (const viewport of [
      { width: 1100, height: 540 },
      { width: 390, height: 480 },
    ]) {
      await page.setViewportSize(viewport);
      for (const [trigger, action] of [
        [`Edit ${name}`, "Save"],
        ["Create new source", "Create source"],
      ]) {
        await page.getByRole("button", { name: trigger, exact: true }).click();
        const dialog = page.getByRole("dialog");
        const title = dialog.getByRole("heading");
        const submit = dialog.getByRole("button", { name: action, exact: true });
        await expect(title).toBeInViewport({ ratio: 1 });
        await expect(submit).toBeInViewport({ ratio: 1 });

        const deliveryId = dialog.getByRole("textbox", { name: /Delivery ID header/ });
        await deliveryId.scrollIntoViewIfNeeded();
        await expect(deliveryId).toBeInViewport({ ratio: 1 });
        await expect(title).toBeInViewport({ ratio: 1 });
        await expect(submit).toBeInViewport({ ratio: 1 });
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      }
    }
  } finally {
    await page.request.delete(`/api/event-sources/${id}`);
  }
});
