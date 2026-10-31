import type { Locator, Page } from "@playwright/test";
import type { ArtifactDetail } from "../src/types/artifact";

import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

async function expectTouchTarget(control: Locator) {
  await expect(control).toBeVisible();
  const box = await control.boundingBox();
  if (!box) throw new Error("The touch control has no visible bounds");
  // Chromium can return 43.999998 for a 44px transformed box. Keep the target
  // requirement while comparing at a thousandth of a CSS pixel.
  expect(Math.round(box.width * 1000) / 1000).toBeGreaterThanOrEqual(44);
  expect(Math.round(box.height * 1000) / 1000).toBeGreaterThanOrEqual(44);
}

async function expectContained(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBe(0);
  const main = page.locator("main");
  await expect(main).toBeVisible();
  expect(await main.evaluate((element) => element.scrollWidth - element.clientWidth)).toBe(0);
  expect((await main.boundingBox())?.y).toBeGreaterThanOrEqual(0);
}

for (const platform of ["ios", "android"] as const) {
  test.describe(`${platform} surfaces`, () => {
    test.use({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      storageState: AUTH_STATE,
    });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((platform) => {
        window.__AGENTICOS_SHELL__ = {
          platform,
          window: "main",
          version: "0.1.0",
          vibrancy: false,
        };
        document.addEventListener("DOMContentLoaded", () => {
          // Exercise the layout contracts around a notch/status bar and home indicator.
          document.documentElement.style.setProperty(
            "--shell-inset-top",
            platform === "ios" ? "54px" : "28px",
          );
          document.documentElement.style.setProperty("--shell-inset-bottom", "24px");
        });
      }, platform);
      // Reuse the authenticated setup: these layout checks must not exhaust
      // the real sign-in rate limit with a new session before every test.
      await page.goto("/dashboard");
      await expect(page.getByRole("dialog", { name: "We use cookies" })).toHaveCount(0);
      await expect(page).toHaveURL(/\/dashboard(?:\?.*)?$/, { timeout: 30_000 });
    });

    test("keeps notifications inside the phone from the header and navigation drawer", async ({
      page,
    }) => {
      await page.route("**/api/notifications/unread-count", async (route) =>
        route.fulfill({ json: { count: 30, approximate: false } }),
      );
      await page.route("**/api/notifications?*", async (route) =>
        route.fulfill({ json: { items: [], next_cursor: null } }),
      );
      await page.route("**/api/notifications", async (route) =>
        route.fulfill({
          json: {
            items: Array.from({ length: 30 }, (_, index) => ({
              id: `phone-notification-${index}`,
              event_type: "run_completed",
              summary: `Notification ${index + 1}: an agent finished its work`,
              context_url: "/agents",
              read_at: "2026-10-24T00:00:00Z",
              created_at: "2026-10-24T00:00:00Z",
            })),
            next_cursor: null,
          },
        }),
      );
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        for (const fromDrawer of [false, true]) {
          if (fromDrawer) await page.getByRole("button", { name: "Toggle menu" }).tap();
          const trigger = fromDrawer
            ? page.getByRole("dialog").getByRole("button", { name: /^Notifications/ })
            : page.locator("header").getByRole("button", { name: /^Notifications/ });
          await trigger.tap();
          const panel = page.getByRole("dialog", { name: "Notifications", exact: true });
          await expect(panel).toBeVisible();
          await expect(
            panel.getByText("Notification 1: an agent finished its work", { exact: true }),
          ).toBeVisible();
          const box = await panel.boundingBox();
          if (!box) throw new Error("Notifications has no bounds");
          expect(box.x).toBeGreaterThanOrEqual(0);
          expect(box.x + box.width).toBeLessThanOrEqual(width);
          expect(box.y).toBeGreaterThanOrEqual(platform === "ios" ? 54 : 28);
          expect(box.y + box.height).toBeLessThanOrEqual(844);
          const list = panel.locator(".overflow-y-auto");
          expect(
            await list.evaluate((element) => element.scrollHeight > element.clientHeight),
          ).toBe(true);
          await list.evaluate((element) => {
            element.scrollTop = element.scrollHeight;
          });
          await expect(
            panel.getByText("Notification 30: an agent finished its work", { exact: true }),
          ).toBeVisible();
          if (fromDrawer && width === 320)
            await page.screenshot({ path: test.info().outputPath("notifications-drawer-320.png") });
          const close = panel.getByRole("button", { name: "Close", exact: true });
          await expectTouchTarget(close);
          await close.tap();
          await expect(panel).toHaveCount(0);
          if (fromDrawer)
            await page
              .getByRole("dialog")
              .getByRole("button", { name: "Close", exact: true })
              .tap();
        }
      }
    });

    test("keeps core navigation, menus and phone actions reachable", async ({ page }) => {
      test.setTimeout(60_000);
      await expectTouchTarget(page.getByRole("button", { name: "Me", exact: true }));
      const dismiss = page.getByRole("button", { name: /^Hide the tip/ }).first();
      if (await dismiss.count()) {
        await expectTouchTarget(dismiss);
        await expect(dismiss).toHaveCSS("opacity", "1");
      }
      await page.goto("/agents");
      const more = page.getByRole("button", { name: /^More actions for/ }).first();
      await expectTouchTarget(more);
      const clones: string[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && /\/api\/agents\/[^/]+\/clone$/.test(request.url())) {
          clones.push(request.url());
        }
      });
      await more.tap();
      await expect(page.getByRole("menu")).toBeVisible();
      expect(clones).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("menu")).toBeHidden();
      await page.getByRole("button", { name: "New agent", exact: true }).tap();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expectContained(page);
      await dialog.getByRole("button", { name: "Cancel", exact: true }).tap();
      await expect(dialog).toBeHidden();

      await page.goto("/chat");
      const picker = page.getByRole("button", { name: /^Agent:/ });
      await expectTouchTarget(picker);
      await picker.tap();
      await expect(page.getByRole("radiogroup")).toBeVisible();
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Add to message", exact: true }).tap();
      await expect(
        page.getByRole("dialog").getByRole("button", { name: "Files", exact: true }),
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expectContained(page);
    });

    test("uses touch targets throughout settings and preserves the viewport", async ({ page }) => {
      test.setTimeout(60_000);
      await page.goto("/settings/profile");
      await expectTouchTarget(page.getByRole("radio", { name: "Automatic colour", exact: true }));
      const theme = page
        .locator('[data-tour="settings-appearance"]')
        .getByRole("radio", { name: "Dark", exact: true });
      await theme.scrollIntoViewIfNeeded();
      await expectTouchTarget(theme);
      await theme.tap();
      await expect(theme).toBeChecked();
      await expectContained(page);
      await page.goto("/settings/notifications");
      const switches = page.getByRole("switch");
      await expect(switches.first()).toBeVisible();
      for (const control of await switches.all()) await expectTouchTarget(control);
      await expectContained(page);
      await page.goto("/settings/mcp");
      const browser = page.getByRole("radio", { name: "Through the browser", exact: true });
      await browser.scrollIntoViewIfNeeded();
      await expectTouchTarget(browser);
      const copy = page.getByRole("button", { name: "Copy", exact: true }).first();
      await expectTouchTarget(copy);
      await expectContained(page);
    });

    test("keeps phone catalog filters compact and preserves their selection", async ({ page }) => {
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/agents");
        const toggle = page.getByRole("button", { name: /^Filters/ });
        await expectTouchTarget(toggle);
        const status = page.getByRole("combobox", { name: "Filter by status" });
        await expect(status).toBeHidden();
        await toggle.tap();
        await expect(status).toBeVisible();
        await status.tap();
        await page.getByRole("option", { name: "Published", exact: true }).tap();
        await toggle.tap();
        await expect(status).toBeHidden();
        await expect(toggle).toHaveText("Filters 1");
        await toggle.tap();
        await expect(status).toContainText("Published");
        const title = page.getByRole("heading", { level: 3 }).first();
        await expect(title).toBeVisible();
        expect(await title.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
          true,
        );
        await expectContained(page);
        await page.screenshot({ path: test.info().outputPath(`agent-filters-${width}.png`) });
      }
    });

    test("keeps the project phone actions on one row with secondary actions in More", async ({
      page,
    }) => {
      await page.goto("/projects");
      const project = page.locator("main a[href*='/projects/']").first();
      await expect(project).toBeVisible();
      const href = await project.getAttribute("href");
      if (!href) throw new Error("Expected the project's detail link");
      const id = href.split("/").at(-1);
      await page.route(`**/api/projects/${id}/files`, (route) =>
        route.fulfill({
          json: {
            scope: "project",
            backend: "state",
            owner_label: "This project",
            items: [],
            total: 0,
            bytes_total: 0,
            unreadable_reason: null,
            truncated: false,
          },
        }),
      );
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(href);
        const add = page.getByRole("button", { name: "Upload files", exact: true });
        const more = page.getByRole("button", { name: "More", exact: true });
        await expectTouchTarget(add);
        await expectTouchTarget(more);
        expect((await add.boundingBox())?.y).toBe((await more.boundingBox())?.y);
        await expect(page.getByRole("button", { name: "Upload folder", exact: true })).toBeHidden();
        await expect(page.getByRole("button", { name: "New folder", exact: true })).toBeHidden();
        await more.tap();
        await page.getByRole("menuitem", { name: "New folder", exact: true }).tap();
        const dialog = page.getByRole("dialog");
        await expect(dialog).toBeVisible();
        await dialog.getByRole("button", { name: "Cancel", exact: true }).tap();
        await expect(dialog).toBeHidden();
        await expectContained(page);
        await page.screenshot({ path: test.info().outputPath(`project-actions-${width}.png`) });
      }
    });

    test("gives app preview actions vertical breathing room and equal touch targets", async ({
      page,
    }) => {
      // This is a toolbar-layout contract. Publishing apps requires an agent
      // run, so use a typed display fixture rather than a live model call.
      const id = "00000000-0000-4000-8000-000000000001";
      const version = {
        id: "00000000-0000-4000-8000-000000000002",
        number: 1,
        media_type: "text/html" as const,
        size_bytes: 48,
        run_id: null,
        created_at: new Date().toISOString(),
      };
      const artifact: ArtifactDetail = {
        id,
        name: "layout-report",
        title: "Layout report",
        visibility: "private",
        owner_user_id: null,
        agent_id: null,
        environment_id: null,
        environment_name: null,
        public_url: null,
        published_at: version.created_at,
        created_at: version.created_at,
        updated_at: null,
        current_version: version,
        can_edit: false,
        following: false,
        public_link: {
          expires_at: null,
          pinned_version_id: null,
          pinned_version: null,
          password_protected: false,
          view_count: 0,
          last_viewed_at: null,
          embed_origins: [],
          embed_url: null,
        },
      };
      await page.route(`**/api/apps/${id}`, (route) => route.fulfill({ json: artifact }));
      await page.route(`**/api/apps/${id}/versions`, (route) =>
        route.fulfill({ json: { items: [version], total: 1 } }),
      );
      await page.route(`**/api/apps/${id}/view*`, (route) =>
        route.fulfill({
          json: {
            url: new URL("/e2e-app.html", page.url()).href,
            expires_at: new Date(Date.now() + 60_000).toISOString(),
            version,
          },
        }),
      );
      await page.route("**/e2e-app.html", (route) =>
        route.fulfill({ contentType: "text/html", body: "<!doctype html><h1>Layout report</h1>" }),
      );
      await page.route(`**/api/apps/${id}/sharing`, (route) =>
        route.fulfill({
          json: {
            resource_type: "artifact",
            resource_id: id,
            owner_user_id: null,
            visibility: "private",
            grants: [],
          },
        }),
      );
      const href = `/apps/${id}`;
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(href);
        const share = page.getByRole("button", { name: "Share", exact: true });
        await expectTouchTarget(share);
        const follow = page.getByRole("button", { name: /^(Follow|Unfollow)$/ });
        await expectTouchTarget(follow);
        const bar = page.locator("header").filter({ has: share });
        const bounds = await bar.boundingBox();
        const action = await share.boundingBox();
        if (!bounds || !action) throw new Error("Expected the app toolbar bounds");
        expect(action.y - bounds.y).toBeGreaterThanOrEqual(8);
        expect(bounds.y + bounds.height - action.y - action.height).toBeGreaterThanOrEqual(8);
        expect((await follow.boundingBox())?.height).toBe(action.height);
        await page.screenshot({ path: test.info().outputPath(`app-toolbar-${width}.png`) });
        await share.tap();
        await expect(page.getByRole("dialog")).toBeVisible();
        await page.keyboard.press("Escape");
        await expectContained(page);
      }
    });

    test("keeps Skills filters folded and resource actions below the card content", async ({
      page,
    }) => {
      for (const [width, path] of [
        [320, "/skills"],
        [390, "/skills"],
        [320, "/context"],
        [390, "/context"],
      ] as const) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(path);
        const filters = page.getByRole("button", { name: /^Filters/ });
        await expectTouchTarget(filters);
        const sort = page.getByRole("button", { name: "Recently updated", exact: true });
        await expect(sort).toBeHidden();
        await filters.tap();
        await expect(sort).toBeVisible();
        await filters.tap();
        const card = page.locator("main .peek-card").first();
        await expect(card).toBeVisible();
        const add = card.getByRole("button", { name: "Add to an agent", exact: true });
        await expectTouchTarget(add);
        const content = await card.locator(":scope > button").boundingBox();
        const action = await add.boundingBox();
        if (!content || !action) throw new Error("Expected the resource card's bounds");
        expect(action.y).toBeGreaterThanOrEqual(content.y + content.height);
        await expectContained(page);
        await page.screenshot({ path: test.info().outputPath(`${path.slice(1)}-${width}.png`) });
      }
    });

    test("contains CSV exports inside every Activity tab header", async ({ page }) => {
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/runs");
        for (const name of [/^Runs/, /^Approvals/, /^Spend/]) {
          await page.getByRole("tab", { name }).tap();
          const csv = page.getByRole("button", { name: "Export CSV", exact: true });
          await csv.scrollIntoViewIfNeeded();
          await expectTouchTarget(csv);
          expect(await csv.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
            true,
          );
          const bounds = await csv.boundingBox();
          if (!bounds) throw new Error("Expected the export button bounds");
          expect(bounds.x).toBeGreaterThanOrEqual(12);
          expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 12);
          await expectContained(page);
          if (name.source === "^Spend") {
            const cost = await page
              .getByRole("columnheader", { name: "Cost", exact: true })
              .first()
              .boundingBox();
            if (!cost) throw new Error("Expected the spend cost column");
            expect(cost.x + cost.width).toBeLessThanOrEqual(width);
          }
        }
        await page.screenshot({ path: test.info().outputPath(`activity-${width}.png`) });
      }
    });
  });
}
