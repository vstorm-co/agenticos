import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import { OWNER_EMAIL, OWNER_PASSWORD } from "./helpers";

/** Validate only the listing fields this pointer regression actually uses. */
function listingItems(value: unknown): Record<string, unknown>[] {
  if (!value || typeof value !== "object" || !("items" in value) || !Array.isArray(value.items)) {
    throw new Error("Expected a paginated listing");
  }
  return value.items.map((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("Expected a listing item");
    }
    return Object.fromEntries(Object.entries(item));
  });
}

function listingText(value: unknown): string {
  if (typeof value !== "string") throw new Error("Expected a string listing field");
  return value;
}

/** Wait for finite entrance animations, leaving live activity indicators alone. */
async function settleEntrances(page: Page) {
  await page.evaluate(async () => {
    const entrances = document
      .getAnimations()
      .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity);
    await Promise.allSettled(entrances.map((animation) => animation.finished));
  });
}

/** Click where a person clicks, without Playwright scrolling around an overlay. */
async function clickCenter(page: Page, control: Locator) {
  await expect(control).toBeVisible();
  await settleEntrances(page);
  const box = await control.boundingBox();
  if (!box) throw new Error("The control has no visible bounds");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
}

/** Visible controls must receive their own pointer events, including after scrolling. */
async function expectReachableButtons(page: Page): Promise<number> {
  await settleEntrances(page);
  const inspected = await page.getByRole("button").evaluateAll((buttons) =>
    buttons.flatMap((button) => {
      if (button.matches(":disabled, [aria-disabled='true']")) return [];
      const rect = button.getBoundingClientRect();
      const x = rect.x + rect.width / 2;
      const y = rect.y + rect.height / 2;
      if (!rect.width || !rect.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight)
        return [];
      // Overflow-clipped descendants of collapsed groups are still in the DOM.
      for (let parent = button.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        const bounds = parent.getBoundingClientRect();
        if (
          (style.overflowX !== "visible" && (x < bounds.left || x >= bounds.right)) ||
          (style.overflowY !== "visible" && (y < bounds.top || y >= bounds.bottom))
        )
          return [];
      }
      const hit = document.elementFromPoint(x, y);
      return hit && button.contains(hit)
        ? [null]
        : [
            {
              control: button.getAttribute("aria-label") || button.textContent?.trim(),
              blocker: hit?.getAttribute("class"),
            },
          ];
    }),
  );
  expect(
    inspected.filter((item) => item !== null),
    "another layer intercepts the center of a visible button",
  ).toEqual([]);
  return inspected.length;
}

test.describe("desktop pointer controls", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });
  test.beforeEach(async ({ page }) => {
    // A separate browser context exercises the actual console's desktop CSS,
    // without inspecting or controlling a running native app.
    await page.addInitScript(() => {
      window.__AGENTICOS_SHELL__ = {
        platform: "macos",
        window: "main",
        version: "0.2.0",
        vibrancy: false,
      };
    });
    await page.goto("/login");
    await page.getByLabel("Email", { exact: true }).fill(OWNER_EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Login", exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard(?:\?.*)?$/, { timeout: 30_000 });
  });

  test("opens New agent and templates from their centers, then closes both dialogs", async ({
    page,
  }) => {
    const listing = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/agents" &&
        response.request().method() === "GET" &&
        // Dashboard's agent query may still be in flight after sign-in. Its
        // response body belongs to the document that goto is about to discard.
        new URL(response.request().headers()["referer"] ?? "about:blank").pathname.endsWith(
          "/agents",
        ),
    );
    await page.goto("/agents");
    const response = await listing;
    expect(response.ok()).toBe(true);
    const items = listingItems(await response.json());
    expect(items.length).toBeGreaterThan(0);
    await expect(page.locator("main")).toContainText(listingText(items[0]?.name));
    await expectReachableButtons(page);
    await clickCenter(page, page.getByRole("button", { name: "New agent", exact: true }));
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "Name", exact: true })).toBeVisible();
    await clickCenter(page, dialog.getByRole("button", { name: "Cancel", exact: true }));
    await expect(dialog).toBeHidden();
    await clickCenter(page, page.getByRole("button", { name: "Agent templates", exact: true }));
    await expect(dialog).toBeVisible();
    await clickCenter(page, dialog.getByRole("button", { name: "Close", exact: true }));
    await expect(dialog).toBeHidden();
  });

  for (const width of [1440, 900]) {
    test(`keeps buttons reachable across desktop pages and after scrolling at ${width}px`, async ({
      page,
    }) => {
      test.setTimeout(60_000); // Eight layouts with real data; keep each width independently bounded.
      await page.setViewportSize({ width, height: width === 900 ? 640 : 1000 });
      for (const [path, api] of [
        ["/agents", "/api/agents"],
        ["/projects", "/api/projects"],
        ["/skills", "/api/skills"],
        ["/context", "/api/context"],
        ["/rag", "/api/kb"],
        ["/documents", "/api/sandbox-workspaces/files"],
        ["/routines", "/api/triggers"],
        ["/runs", "/api/runs"],
      ] as const) {
        const data = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === api && response.request().method() === "GET",
        );
        await page.goto(path);
        expect((await data).ok()).toBe(true);
        await expect(page.locator("main").getByRole("heading", { level: 1 }).first()).toBeVisible();
        const count = await expectReachableButtons(page);
        await page.locator("#main").evaluate((main) => {
          main.scrollTop = main.scrollHeight;
        });
        await expectReachableButtons(page);
        console.log(`${width}px ${path}: ${count} visible button elements checked`);
      }
    });
  }

  test("closes a recorded run from the center of its X button", async ({ page }) => {
    const listing = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/runs" &&
        response.request().method() === "GET" &&
        // Ignore Dashboard's still-in-flight listing from the previous document.
        new URL(response.request().headers()["referer"] ?? "about:blank").pathname.endsWith(
          "/runs",
        ),
    );
    await page.goto("/runs");
    const response = await listing;
    expect(response.ok()).toBe(true);
    const first = listingItems(await response.json())[0];
    test.skip(!first, "This deployment has no recorded runs yet");
    if (!first) return;
    await page.goto(`/runs?run=${encodeURIComponent(listingText(first.id))}`);
    const panel = page.getByRole("complementary", { name: "Run detail", exact: true });
    await expect(panel).toBeVisible();
    await expectReachableButtons(page);
    await clickCenter(
      page,
      panel.getByRole("button", { name: "Close the run detail", exact: true }),
    );
    await expect(panel).toBeHidden();
  });

  test("keeps an opened app below the native controls with a usable toolbar", async ({ page }) => {
    test.setTimeout(60_000);
    const listing = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/apps" && response.request().method() === "GET",
    );
    await page.goto("/apps");
    const response = await listing;
    expect(response.ok()).toBe(true);
    const app = listingItems(await response.json()).find(
      (item) => item.current_version !== null && typeof item.current_version === "object",
    );
    test.skip(!app, "This deployment has no published apps yet");
    if (!app) return;
    for (const width of [1440, 900]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`/apps/${encodeURIComponent(listingText(app.id))}`);
      await expect(
        page.getByRole("heading", { name: listingText(app.title), exact: true }),
      ).toBeVisible();
      await expect(page.locator("iframe")).toBeVisible();
      const back = page.getByRole("link", { name: "Back to apps", exact: true });
      await expect(back).toBeVisible();
      const bounds = await back.boundingBox();
      expect(bounds?.y, "native controls occupy the first 48 pixels").toBeGreaterThanOrEqual(48);
      await expectReachableButtons(page);
      await clickCenter(page, page.getByRole("button", { name: "Share", exact: true }));
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();

      // The reserved row is native chrome; the web viewer stays edge to edge.
      await page.locator("html").evaluate((root) => root.removeAttribute("data-shell"));
      await expect(page.locator(".macos-window-controls")).toBeHidden();
      expect((await back.boundingBox())?.y).toBeLessThan(48);
      await clickCenter(page, back);
      await expect(page).toHaveURL(/\/apps$/);
    }
  });

  test("selects every desktop style from the account menu and keeps it after reload", async ({
    page,
  }, testInfo) => {
    test.setTimeout(60_000);
    await page.goto("/settings/profile");
    const appearance = page.locator('[data-tour="settings-appearance"]');
    await expect(appearance).toBeVisible();
    for (const theme of ["Light", "Dark"]) {
      await page.setViewportSize(
        theme === "Light" ? { width: 1440, height: 1000 } : { width: 900, height: 640 },
      );
      await appearance.getByRole("radio", { name: theme, exact: true }).click();
      for (const name of ["Standard", "Glass", "Graphite", "Midnight", "Paper"]) {
        await page
          .locator("aside")
          .getByRole("button", { name: new RegExp(OWNER_EMAIL) })
          .click();
        await page.getByRole("menuitem", { name: /^Appearance/ }).click();
        const item = page.getByRole("menuitemradio", { name, exact: true });
        await expect(item).toBeVisible();
        await item.click();
        if (name === "Standard")
          await expect(page.locator("html")).not.toHaveAttribute("data-look");
        else await expect(page.locator("html")).toHaveAttribute("data-look", name.toLowerCase());
        await expect(appearance.getByRole("radio", { name: new RegExp(`^${name}`) })).toBeChecked();
        await expect(appearance.getByRole("radio", { name: theme, exact: true })).toBeChecked();
      }
      await page.reload();
      await expect(appearance.getByRole("radio", { name: /^Paper/ })).toBeChecked();
      await expect(appearance.getByRole("radio", { name: theme, exact: true })).toBeChecked();
      await appearance.scrollIntoViewIfNeeded();
      await page
        .locator("aside")
        .getByRole("button", { name: new RegExp(OWNER_EMAIL) })
        .click();
      await page.getByRole("menuitem", { name: /^Appearance/ }).click();
      await expect(page.getByRole("menuitemradio", { name: "Paper", exact: true })).toBeChecked();
      await settleEntrances(page);
      await page.screenshot({ path: testInfo.outputPath(`appearance-${theme.toLowerCase()}.png`) });
      await page.keyboard.press("Escape");
      await page.keyboard.press("Escape");
    }
  });

  test("scrolls a large file listing without moving the chat or its close control", async ({
    page,
  }) => {
    const listing = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/conversations" &&
        response.request().method() === "GET" &&
        new URL(response.request().headers()["referer"] ?? "about:blank").pathname.endsWith(
          "/chat",
        ),
    );
    await page.goto("/chat");
    const response = await listing;
    expect(response.ok()).toBe(true);
    const conversations = listingItems(await response.json());
    expect(conversations.length).toBeGreaterThan(0);
    const id = listingText(conversations[0]?.id);
    // Use an existing authorized chat, with a deterministic large workspace.
    // No local documents or model call is needed for this layout regression.
    await page.route(`**/api/conversations/${id}/workspace`, (route) =>
      route.fulfill({
        json: {
          scope: "conversation",
          backend: "state",
          owner_label: "This conversation",
          total: 120,
          bytes_total: 12000,
          bytes_limit: null,
          unreadable_reason: null,
          items: Array.from({ length: 120 }, (_, index) => ({
            path: `/report-${String(index).padStart(3, "0")}-${"long-name-".repeat(12)}.md`,
            size: 100,
            is_dir: false,
            modified_at: null,
            preview: null,
            thumbnail: null,
          })),
        },
      }),
    );
    await page.goto(`/chat?id=${encodeURIComponent(id)}`);
    const composer = page.getByRole("textbox", { name: "Type a message...", exact: true });
    await expect(composer).toBeVisible();
    const before = await composer.boundingBox();
    await page.getByRole("button", { name: /^Show the files/ }).click();
    const panel = page
      .getByRole("complementary")
      .filter({ has: page.getByRole("button", { name: "Close the file panel" }) });
    const close = panel.getByRole("button", { name: "Close the file panel" });
    await expect(panel.getByRole("listitem")).toHaveCount(120);
    await settleEntrances(page);
    const initialClose = await close.boundingBox();
    const scrollport = panel.locator(".overflow-y-auto");
    const geometry = await panel.evaluate((element) => ({
      bottom: element.getBoundingClientRect().bottom,
      viewport: innerHeight,
      overflow: element.scrollWidth > element.clientWidth,
    }));
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewport);
    expect(geometry.overflow).toBe(false);
    await scrollport.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect(panel.getByRole("listitem").last()).toBeInViewport();
    expect(await close.boundingBox()).toEqual(initialClose);
    expect((await composer.boundingBox())?.y).toBe(before?.y);
    await clickCenter(page, close);
    await expect(panel).toBeHidden();
  });
});
