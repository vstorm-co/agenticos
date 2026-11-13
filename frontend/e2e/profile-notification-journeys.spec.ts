import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import { AUTH_STATE, json, rowsAt } from "./helpers";
import type { User } from "../src/types";

async function heldRefusal(page: Page, path: string, method: "GET" | "PATCH" | "POST") {
  const held = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const pattern = `**${path}`;
  await page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.continue();
    started.resolve();
    await held.promise;
    await route.fulfill({ status: 403, json: { detail: "Controlled profile/settings refusal" } });
  });
  return {
    started: started.promise,
    release: () => held.resolve(),
    remove: () => page.unroute(pattern),
  };
}

for (const device of [
  { name: "desktop", viewport: { width: 1440, height: 1000 }, phone: false },
  { name: "phone", viewport: { width: 320, height: 740 }, phone: true },
] as const) {
  test.describe(device.name, () => {
    test.use({
      storageState: AUTH_STATE,
      viewport: device.viewport,
      isMobile: device.phone,
      hasTouch: device.phone,
      reducedMotion: "reduce",
      actionTimeout: 15_000,
    });
    test("profile and notification choices survive refusal, retry, navigation and reload", async ({
      page,
    }) => {
      test.setTimeout(150_000);
      const identityReady = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/me/channel-link" && response.status() === 200,
      );
      await page.goto("/settings/profile");
      await identityReady;
      await expect(page.getByLabel("Display name", { exact: true })).toBeVisible();
      const original = await json<User>(page.request, "/api/users/me");
      const preferences = await rowsAt(page.request, "/api/notifications/preferences");
      const before = (channel: string) => {
        const row = preferences.find(
          (item) => item.event_type === "run_completed" && item.channel === channel,
        );
        return typeof row?.enabled === "boolean" ? row.enabled : true;
      };
      const name = `UI Profile ${device.name} ${Date.now().toString(36)}`;
      const color = original.avatar_color === 3 ? 4 : 3;
      const updated = (method: "PATCH" | "POST", path: string) =>
        page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === path &&
            response.request().method() === method &&
            response.ok(),
        );
      let release: (() => void) | undefined;
      try {
        await page.getByRole("button", { name: "Fallback colour", exact: true }).click();
        const colorHeld = await heldRefusal(page, "/api/users/me", "PATCH");
        release = colorHeld.release;
        await page.getByRole("radio", { name: `Colour ${color}`, exact: true }).click();
        await colorHeld.started;
        await expect(page.getByLabel("Display name", { exact: true })).toBeDisabled();
        await expect(page.getByLabel("Your role", { exact: true })).toBeDisabled();
        colorHeld.release();
        await expect(page.getByLabel("Display name", { exact: true })).toBeEnabled();
        await colorHeld.remove();
        const colorSaved = updated("PATCH", "/api/users/me");
        await page.getByRole("radio", { name: `Colour ${color}`, exact: true }).click();
        await colorSaved;
        await expect(
          page.getByRole("radio", { name: `Colour ${color}`, exact: true }),
        ).toBeChecked();
        await page.emulateMedia({ forcedColors: "active" });
        expect(
          await page
            .getByRole("radio", { name: `Colour ${color}`, exact: true })
            .evaluate((element) => getComputedStyle(element).appearance),
        ).toBe("auto");
        await page.emulateMedia({ forcedColors: "none" });

        await page.getByLabel("Display name", { exact: true }).fill(name);
        const nameHeld = await heldRefusal(page, "/api/users/me", "PATCH");
        release = nameHeld.release;
        await page.getByLabel("Display name", { exact: true }).press("Enter");
        await nameHeld.started;
        await expect(page.getByLabel("Email", { exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
        nameHeld.release();
        await expect(page.getByLabel("Display name", { exact: true })).toBeEnabled();
        await nameHeld.remove();
        await expect(page.getByLabel("Display name", { exact: true })).toHaveValue(name);
        const nameSaved = updated("PATCH", "/api/users/me");
        await page.getByLabel("Display name", { exact: true }).press("Enter");
        await nameSaved;

        await page.getByLabel("Your role", { exact: true }).fill("Customer experience lead");
        await page
          .getByLabel("What you work on", { exact: true })
          .fill("Customer handovers and reliable support.");
        await page.getByRole("combobox", { name: "Time zone", exact: true }).click();
        await page
          .getByRole("combobox", { name: "Search time zones…", exact: true })
          .fill("Warsaw");
        await page.getByRole("option", { name: "Europe/Warsaw", exact: true }).click();
        for (const day of ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]) {
          const button = page.getByRole("button", { name: day, exact: true });
          if ((await button.getAttribute("aria-pressed")) === "true") await button.click();
        }
        for (const day of ["Mon", "Wed"])
          await page.getByRole("button", { name: day, exact: true }).click();
        await page.getByLabel("Starts at", { exact: true }).fill("08:30");
        await page.getByLabel("Ends at", { exact: true }).fill("16:30");
        const contextHeld = await heldRefusal(page, "/api/users/me", "PATCH");
        release = contextHeld.release;
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await contextHeld.started;
        for (const label of [
          "Display name",
          "Your role",
          "What you work on",
          "Starts at",
          "Ends at",
        ])
          await expect(page.getByLabel(label, { exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Mon", exact: true })).toBeDisabled();
        contextHeld.release();
        await expect(page.getByLabel("Your role", { exact: true })).toBeEnabled();
        await contextHeld.remove();
        await expect(page.getByLabel("Ends at", { exact: true })).toHaveValue("16:30");
        const contextSaved = updated("PATCH", "/api/users/me");
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await contextSaved;
        await page.reload();
        await expect(page.getByLabel("Display name", { exact: true })).toHaveValue(name);
        await expect(page.getByLabel("Your role", { exact: true })).toHaveValue(
          "Customer experience lead",
        );
        await expect(page.getByLabel("Starts at", { exact: true })).toHaveValue("08:30");
        await expect(page.getByRole("combobox", { name: "Time zone", exact: true })).toContainText(
          "Europe/Warsaw",
        );
        if (device.phone)
          for (const label of ["Starts at", "Ends at"]) {
            const field = page.getByLabel(label, { exact: true });
            await field.scrollIntoViewIfNeeded();
            const box = await field.boundingBox();
            expect(box).not.toBeNull();
            if (box) {
              expect(box.x).toBeGreaterThanOrEqual(0);
              expect(box.x + box.width).toBeLessThanOrEqual(320);
            }
          }
        const portrait = await heldRefusal(page, "/api/users/me/avatar", "POST");
        release = portrait.release;
        await page
          .getByRole("form", { name: "Personal info", exact: true })
          .locator('input[type="file"]')
          .setInputFiles({
            name: "review.png",
            mimeType: "image/png",
            buffer: Buffer.from(
              "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=",
              "base64",
            ),
          });
        await portrait.started;
        await expect(page.getByLabel("Display name", { exact: true })).toBeDisabled();
        portrait.release();
        await expect(page.getByLabel("Display name", { exact: true })).toBeEnabled();
        await portrait.remove();
        expect((await json<User>(page.request, "/api/users/me")).avatar_url).toBe(
          original.avatar_url,
        );

        const read = await heldRefusal(page, "/api/notifications/preferences", "GET");
        release = read.release;
        await page
          .getByRole("main")
          .getByRole("link", { name: "Notifications", exact: true })
          .click();
        await read.started;
        read.release();
        const panel = page.locator("section").filter({
          has: page.getByRole("heading", { name: "Notification preferences", exact: true }),
        });
        await expect(panel.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
        await expect(panel.getByRole("switch")).toHaveCount(0);
        await read.remove();
        await panel.getByRole("button", { name: "Retry", exact: true }).click();
        await expect(
          panel.getByRole("switch", { name: "Run completed - Email", exact: true }),
        ).toBeEnabled();
        await panel.getByRole("button", { name: "Next page", exact: true }).click();
        await expect(
          panel.getByRole("heading", { name: "MCP server answering again", exact: true }),
        ).toBeInViewport({ ratio: 1 });
        await expect(
          panel.getByRole("switch", { name: "Run completed - Email", exact: true }),
        ).toHaveCount(0);
        const search = panel.getByPlaceholder("Find notifications…");
        await search.fill("unmatched-event-xyz");
        await expect(panel.getByText("No matching notifications", { exact: true })).toBeVisible();
        await panel.getByRole("button", { name: "Clear search", exact: true }).last().click();
        await search.fill("Run completed");

        const budget = page.getByRole("switch", { name: "Budget alerts", exact: true });
        const budgetHeld = await heldRefusal(page, "/api/users/me", "PATCH");
        release = budgetHeld.release;
        await budget.click();
        await budgetHeld.started;
        await expect(budget).toBeDisabled();
        await expect(
          panel.getByRole("switch", { name: "Run completed - In-app", exact: true }),
        ).toBeEnabled();
        budgetHeld.release();
        await expect(budget).toBeEnabled();
        await budgetHeld.remove();
        await expect(budget).toBeChecked({ checked: original.notify_budget_alerts ?? true });
        const budgetSaved = updated("PATCH", "/api/users/me");
        await budget.click();
        await budgetSaved;

        const chatHeld = await heldRefusal(page, "/api/notifications/preferences", "PATCH");
        release = chatHeld.release;
        await panel.getByRole("switch", { name: "Run completed - Slack", exact: true }).click();
        await chatHeld.started;
        await expect(
          panel.getByRole("switch", { name: "Run completed - Slack", exact: true }),
        ).toBeDisabled();
        await panel
          .getByRole("combobox", { name: "Chat channel preferences", exact: true })
          .click();
        await page.getByRole("option", { name: "Mattermost", exact: true }).click();
        await expect(
          panel.getByRole("switch", { name: "Run completed - Mattermost", exact: true }),
        ).toBeEnabled();
        chatHeld.release();
        await chatHeld.remove();
        const chatSaved = updated("PATCH", "/api/notifications/preferences");
        await panel
          .getByRole("switch", { name: "Run completed - Mattermost", exact: true })
          .click();
        await chatSaved;
        const emailSaved = updated("PATCH", "/api/notifications/preferences");
        await panel.getByRole("switch", { name: "Run completed - Email", exact: true }).click();
        await emailSaved;
        await page.reload();
        await expect(budget).toBeChecked({ checked: !(original.notify_budget_alerts ?? true) });
        await page.getByPlaceholder("Find notifications…").fill("Run completed");
        await expect(
          panel.getByRole("switch", { name: "Run completed - Email", exact: true }),
        ).toBeChecked({ checked: !before("email") });
        await panel
          .getByRole("combobox", { name: "Chat channel preferences", exact: true })
          .click();
        await page.getByRole("option", { name: "Mattermost", exact: true }).click();
        await expect(
          panel.getByRole("switch", { name: "Run completed - Mattermost", exact: true }),
        ).toBeChecked({ checked: !before("mattermost") });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
          device.viewport.width,
        );
        await page.getByRole("main").getByRole("link", { name: "Profile", exact: true }).click();
        await expect(page.getByLabel("Display name", { exact: true })).toHaveValue(name);
        await expect(page.getByLabel("Ends at", { exact: true })).toHaveValue("16:30");
      } finally {
        release?.();
        const restored = await page.request.patch("/api/users/me", {
          data: {
            full_name: original.full_name ?? null,
            avatar_color: original.avatar_color ?? null,
            job_title: original.job_title ?? null,
            about: original.about ?? null,
            time_zone: original.time_zone ?? null,
            working_hours: original.working_hours ?? null,
            notify_budget_alerts: original.notify_budget_alerts ?? true,
          },
        });
        expect(restored.ok()).toBe(true);
        for (const channel of ["email", "mattermost"])
          expect(
            (
              await page.request.patch("/api/notifications/preferences", {
                data: { event_type: "run_completed", channel, enabled: before(channel) },
              })
            ).ok(),
          ).toBe(true);
      }
    });
  });
}
