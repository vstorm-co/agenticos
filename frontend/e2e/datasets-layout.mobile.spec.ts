import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import { AUTH_STATE, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE });

async function fitsPage(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => innerWidth),
  );
}

test("case editing keeps fields and save reachable on narrow and short screens", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  const name = `Responsive dataset ${Date.now().toString(36)} ${"long-name-".repeat(7)}`;
  const question = `Responsive question ${Date.now().toString(36)}`;
  const longAnswer = `https://example.com/${"unbroken-answer-".repeat(40)}`;
  await page.goto("/datasets");
  await page.getByRole("button", { name: "New dataset", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: /^Name/ }).fill(name);
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  const datasetUrl = page.url().split("?")[0];
  await page
    .getByRole("tabpanel", { name: "Cases", exact: true })
    .getByRole("button", { name: "Add case", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const initialBounds = await dialog.boundingBox();
  if (!initialBounds) throw new Error("The case form has no bounds");
  expect(initialBounds.width).toBeLessThanOrEqual(1024);
  expect(initialBounds.height).toBeLessThan(900);
  await expect(
    dialog.getByRole("textbox", { name: "Reference answer", exact: true }),
  ).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Counter-example", exact: true })).toBeHidden();
  await page.screenshot({
    path: info.outputPath("compact-case-desktop.png"),
    animations: "disabled",
  });
  await dialog.getByRole("textbox", { name: /^User message/ }).fill(question);
  await dialog.getByRole("textbox", { name: "Reference answer", exact: true }).fill(longAnswer);
  await dialog.locator("summary").filter({ hasText: "Conversation context" }).click();
  await dialog.getByRole("button", { name: "Add a turn", exact: true }).click();
  await dialog
    .getByRole("textbox", { name: "Turn 1: what was said", exact: true })
    .fill(longAnswer);
  await dialog.locator("summary").filter({ hasText: "Tool expectations" }).click();
  await dialog.getByRole("button", { name: "Add a tool call", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Call 1: tool", exact: true }).fill("search_kb");
  await dialog.getByRole("button", { name: "Add an argument", exact: true }).click();
  await dialog
    .getByRole("textbox", { name: "Call 1, argument 1: name", exact: true })
    .fill("query");
  await dialog
    .getByRole("textbox", { name: "Call 1, argument 1: value", exact: true })
    .fill(longAnswer);

  for (const width of [320, 390, 1440]) {
    for (const height of [360, 844]) {
      await page.setViewportSize({ width, height });
      await page.screenshot({
        path: info.outputPath(`case-${width}-${height}.png`),
        animations: "disabled",
      });
      await expect
        .poll(async () => (await dialog.boundingBox())?.y ?? -1)
        .toBeGreaterThanOrEqual(0);
      await expect
        .poll(async () => {
          const bounds = await dialog.boundingBox();
          return bounds ? bounds.y + bounds.height : Infinity;
        })
        .toBeLessThanOrEqual(height + 1);
      if (width < 640) {
        await expect
          .poll(async () => (await dialog.boundingBox())?.height ?? 0)
          .toBeGreaterThanOrEqual(height - 50);
      }
      await fitsPage(page);
      const bounds = await dialog.boundingBox();
      expect(bounds).not.toBeNull();
      if (!bounds) throw new Error("The case editor has no visible bounds");
      if (width < 640) expect(bounds.height).toBeGreaterThanOrEqual(height - 50);
      else expect(bounds.width).toBeLessThanOrEqual(1024);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(height + 1);
      const speaker = await dialog
        .getByRole("combobox", { name: "Turn 1: who speaks", exact: true })
        .boundingBox();
      const turn = await dialog
        .getByRole("textbox", { name: "Turn 1: what was said", exact: true })
        .boundingBox();
      if (!speaker || !turn) throw new Error("The conversation turn is missing");
      expect(turn.y).toBeGreaterThanOrEqual(speaker.y + speaker.height);
      expect(turn.width).toBeGreaterThan(speaker.width);
      for (const field of await dialog.locator("input, textarea, [role=combobox]").all()) {
        const fieldBounds = await field.boundingBox();
        if (!fieldBounds) continue;
        expect(fieldBounds.x).toBeGreaterThanOrEqual(bounds.x);
        expect(fieldBounds.x + fieldBounds.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
        if (width < 768 && (await field.getAttribute("role")) !== "combobox") {
          expect(
            await field.evaluate((element) => parseFloat(getComputedStyle(element).fontSize)),
          ).toBeGreaterThanOrEqual(16);
        }
      }
      const save = dialog.getByRole("button", { name: "Save case", exact: true });
      const saveBounds = await save.boundingBox();
      expect(saveBounds).not.toBeNull();
      if (!saveBounds) throw new Error("The save action has no visible bounds");
      expect(saveBounds.y + saveBounds.height).toBeLessThanOrEqual(height);
      await save.scrollIntoViewIfNeeded();
      await expect(save).toBeInViewport();
    }
  }
  await page.setViewportSize({ width: 320, height: 844 });
  await dialog.getByRole("button", { name: "Save case", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: new RegExp(`^${question}`) }).click();
  await expect(
    page.getByRole("dialog").getByRole("link", { name: longAnswer, exact: true }),
  ).toBeVisible();
  await fitsPage(page);
  await page.screenshot({ path: info.outputPath("saved-case-320.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    for (const [view, tab] of [
      ["cases", "Cases"],
      ["generated", "Cases"],
      ["grading", "Settings"],
      ["evals", "Results"],
      ["review", "Results"],
      ["settings", "Settings"],
    ]) {
      await page.goto(`${datasetUrl}?tab=${view}`);
      await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await page.locator("main").evaluate((element) => element.scrollTo(0, 0));
      const panel = page.getByRole("tabpanel", { name: new RegExp(`^${tab}`) });
      await expect
        .poll(
          () =>
            panel.evaluate((element) => {
              const frame = element.closest(".page-enter");
              if (!frame) throw new Error("The dataset tab has no page frame");
              const bottom =
                frame.getBoundingClientRect().bottom -
                parseFloat(getComputedStyle(frame).paddingBottom);
              return Math.abs(element.getBoundingClientRect().bottom - bottom);
            }),
          { message: `${tab} fills the page at ${width}px before expanding` },
        )
        .toBeLessThanOrEqual(1);
      const expand = page.getByRole("button", { name: "Full screen", exact: true });
      if (width >= 768) {
        await expect(expand).toBeHidden();
        await fitsPage(page);
        continue;
      }
      await expand.click();
      const workspace = page.getByRole("dialog", { name, exact: true });
      await expect(workspace).toBeVisible();
      const bounds = await workspace.boundingBox();
      if (!bounds) throw new Error("The dataset workspace has no bounds");
      expect(bounds.x).toBe(0);
      expect(bounds.y).toBe(0);
      expect(bounds.width).toBe(width);
      expect(bounds.height).toBe(844);
      await fitsPage(page);
      await page.screenshot({
        path: info.outputPath(`workspace-${view}-${width}.png`),
        animations: "disabled",
      });
      await page.keyboard.press("Escape");
      await expect(workspace).toHaveCount(0);
      await expect(page.getByRole("tab", { name: new RegExp(`^${tab}`) })).toHaveAttribute(
        "data-state",
        "active",
      );
    }
  }
});

test("dataset gallery fills the page with one card and with no search matches", async ({
  page,
}, info) => {
  const name = `Gallery height ${Date.now().toString(36)}`;
  await page.goto("/datasets");
  await page.getByRole("button", { name: "New dataset", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: /^Name/ }).fill(name);
  await submitDialog(page, {
    dialog,
    submit: dialog.getByRole("button", { name: "Create", exact: true }),
    path: "/api/datasets",
  });
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.goto("/datasets");
  const gallery = page.locator('[data-tour="datasets-list"]');
  const search = page.getByRole("textbox", { name: "Search datasets", exact: true });
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const empty of [false, true]) {
      await search.fill(empty ? `${name}-no-match` : name);
      if (empty)
        await expect(gallery.getByText("No dataset matches", { exact: true })).toBeVisible();
      else
        await expect(
          gallery.getByRole("link", { name: `Open ${name}`, exact: true }),
        ).toBeVisible();
      await expect
        .poll(() =>
          gallery.evaluate((element) => {
            const frame = element.closest(".page-enter");
            if (!frame) throw new Error("The gallery has no page frame");
            const expectedBottom =
              frame.getBoundingClientRect().bottom -
              parseFloat(getComputedStyle(frame).paddingBottom);
            return Math.abs(element.getBoundingClientRect().bottom - expectedBottom);
          }),
        )
        .toBeLessThanOrEqual(1);
      await fitsPage(page);
      await page.screenshot({
        path: info.outputPath(`gallery-${empty ? "empty" : "one-card"}-${width}.png`),
        animations: "disabled",
      });
    }
  }
});

test("agent gallery keeps its full height after filtering to no matches", async ({
  page,
}, info) => {
  const response = page.waitForResponse((answer) => {
    const path = new URL(answer.url()).pathname;
    return path === "/api/agents" && answer.request().method() === "GET" && answer.ok();
  });
  await page.goto("/agents");
  await response;
  const search = page.getByRole("textbox", { name: "Search agents", exact: true });
  await search.fill(`No such agent ${Date.now().toString(36)}`);
  await expect(page.getByText("Nothing matches", { exact: true })).toBeVisible();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator("main").evaluate((element) => element.scrollTo(0, 0));
    await expect
      .poll(() =>
        search.evaluate((element) => {
          const gallery = element.closest(".rounded-xl");
          const frame = element.closest(".page-enter");
          if (!gallery || !frame) throw new Error("The agent gallery has no page frame");
          const bottom =
            frame.getBoundingClientRect().bottom -
            parseFloat(getComputedStyle(frame).paddingBottom);
          return Math.abs(gallery.getBoundingClientRect().bottom - bottom);
        }),
      )
      .toBeLessThanOrEqual(1);
    await fitsPage(page);
    await page.screenshot({
      path: info.outputPath(`agents-empty-${width}.png`),
      animations: "disabled",
    });
  }
});
