import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, json, nowMatching, submitDialog } from "./helpers";

/**
 * The bell (#1598): a live unread badge in the sidebar, and the inbox behind
 * it once opened.
 *
 * `seed.setup.ts` stores four secrets through the Vault dialog, and every one
 * of them writes a mandatory `security_event` - the seed's own vault fixtures
 * double as this spec's seeded rows, so there is no dedicated notification
 * fixture to add. That is also why every test here goes through `/vault`
 * rather than `/dashboard`: the dashboard's own "Active sessions" widget
 * renders a `<ul>` of its own, and the bell's row list would not be the only
 * one on screen there.
 */

test.use({ storageState: AUTH_STATE });

const SECURITY_EVENT_SUMMARY = "A vault secret was created.";

/** The row-variant bell, inside the one `<aside>` landmark this shell has. */
function bellTrigger(page: Page) {
  return page.getByRole("complementary").getByRole("button", { name: /Notifications/ });
}

async function openBell(page: Page) {
  await bellTrigger(page).click();
  await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
}

/** Store one throwaway secret through the Vault dialog - the cheapest real
 * action that writes a fresh, unread `security_event`. */
async function storeThrowawaySecret(page: Page, name: string) {
  await page.getByRole("button", { name: "Add key" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Add a secret")).toBeVisible();

  await dialog.getByRole("button", { name: /^Something else/ }).click();
  await dialog.getByLabel(/^(Which one|Service)$/).click();
  await page.getByRole("option", { name: "Something else", exact: true }).click();

  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("textbox", { name: /API key/i }).fill("sk-e2eNOTIFnotarealkeyatallZZ99");
  await submitDialog(page, {
    dialog,
    submit: dialog.getByRole("button", { name: "Store secret" }),
    path: "/api/secrets",
  });
}

test.describe("Notifications", () => {
  test("lists the security events the seed's own vault secrets produced", async ({ page }) => {
    await page.goto("/vault");

    await openBell(page);

    await expect(page.getByText(SECURITY_EVENT_SUMMARY).first()).toBeVisible();
  });

  test("mark all read clears the badge, and the offer goes with it", async ({ page }) => {
    await page.goto("/vault");

    // Self-sufficient rather than relying on the seed's rows still being
    // unread: an earlier run of this very test (locally, without a fresh
    // database) already marked those read, and this offer only renders while
    // something is unread.
    await storeThrowawaySecret(page, `e2e-notif-markall-${Date.now().toString(36)}`);

    // The badge polls every 60s (`UNREAD_COUNT_POLL_MS`) rather than
    // invalidating on an unrelated write, so a reload - a fresh mount's own
    // first fetch - is what a person would do to see it sooner, too.
    await page.reload();

    await openBell(page);
    await page.getByRole("button", { name: "Mark all read" }).click();

    await expect(bellTrigger(page)).not.toContainText(/\d/);

    // The panel, still open, agrees - the offer itself is gone now that
    // nothing is unread, not just the trigger's own badge.
    await expect(page.getByRole("button", { name: "Mark all read" })).toHaveCount(0);
  });

  test("a fresh security event arrives unread, and clicking its row marks it read live", async ({
    page,
  }) => {
    await page.goto("/vault");

    const before = await json<{ items: { id: string }[] }>(page.request, "/api/notifications");
    const beforeIds = new Set(before.items.map((item) => item.id));

    await storeThrowawaySecret(page, `e2e-notif-${Date.now().toString(36)}`);

    const fresh = await nowMatching(
      page.request,
      "/api/notifications",
      (row) => !beforeIds.has(row.id as string) && row.summary === SECURITY_EVENT_SUMMARY,
      "a fresh security event for the secret just stored",
    );
    expect(fresh.read_at, "a notification this test just produced should start unread").toBeNull();

    const countBefore = await json<{ count: number }>(
      page.request,
      "/api/notifications/unread-count",
    );

    await openBell(page);
    // Newest first (`created_at desc`), so the row this test just produced is
    // the top of the list - clicking it is the same click a person makes.
    await page.locator("li").first().locator("a, button").first().click();

    // Polled, not read once: the client's own cache patch and the server's
    // acceptance of the mark-read write are two different moments, and a
    // single read here would not tell a race from a fix.
    await expect
      .poll(
        async () =>
          (await json<{ count: number }>(page.request, "/api/notifications/unread-count")).count,
        { message: "the unread count never dropped by the one row just marked read" },
      )
      .toBe(countBefore.count - 1);
  });

  test("a row with a destination is a real link to where it happened", async ({ page }) => {
    await page.goto("/vault");

    await openBell(page);
    await page.getByText(SECURITY_EVENT_SUMMARY).first().click();

    // A plain `<a href>` to the deployment's own origin, not a client-side
    // route change - `notification-bell.tsx`'s own reason for using one.
    await expect(page).toHaveURL(/\/vault/);
  });
});
