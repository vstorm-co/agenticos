import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  SEEDED_SKILL_CONTENT,
  SEEDED_SKILL_DESCRIPTION,
  SEEDED_SKILL_NAME,
  pageHeading,
  skillCard,
  submitDialog,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * A skill's save makes a new version on one line, live at once for every agent
 * following that line. The gallery has to list what exists, a skill's page has to
 * open its editor with what is actually stored, and the editor has to say out loud
 * how far a save reaches.
 *
 * `seed.setup.ts` writes the skill these assert on, through this same UI —
 * bootstrap creates none, and a gallery asserted to be empty is a gallery that
 * passes just as happily when the request behind it 502s.
 */

test.describe("Skills", () => {
  for (const width of [390, 1440]) {
    test(`a skill opens in a readable modal with a full-view link at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/skills");
      await skillCard(page, SEEDED_SKILL_NAME).click();
      const modal = page.getByRole("dialog", { name: SEEDED_SKILL_NAME, exact: true });
      await expect(modal).toBeVisible();
      await expect(modal.getByLabel(/Instructions source/)).toHaveValue(SEEDED_SKILL_CONTENT);
      await expect(modal.getByRole("tab", { name: "Version tree", exact: true })).toHaveCount(0);
      await expect(
        modal.getByRole("heading", { name: SEEDED_SKILL_NAME, exact: true }),
      ).toBeVisible();
      const bounds = await modal.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      const fullView = modal.getByRole("button", { name: "Open full view", exact: true });
      await fullView.click();
      await expect(page).toHaveURL(/\/skills\/[^?]+\?tab=content$/);
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(pageHeading(page, SEEDED_SKILL_NAME)).toBeVisible();
    });
  }

  test("the gallery lists the organization's skills", async ({ page }) => {
    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();

    const card = skillCard(page, SEEDED_SKILL_NAME);
    await expect(card).toBeVisible();
    // The description is on the card because it is the only part the model sees
    // before deciding whether to open the skill — content, not decoration.
    await expect(card).toContainText(SEEDED_SKILL_DESCRIPTION);
    // A block utility once overrode line-clamp: the CSS advertised two lines
    // while the real browser expanded long descriptions into giant cards.
    const description = card.getByText(SEEDED_SKILL_DESCRIPTION, { exact: true });
    const dimensions = await description.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      contentHeight: element.scrollHeight,
      lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
    }));
    expect(dimensions.contentHeight).toBeGreaterThan(dimensions.height);
    expect(dimensions.height).toBeLessThanOrEqual(dimensions.lineHeight * 2 + 1);
  });

  test("opening a skill shows what the model actually reads", async ({ page }) => {
    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();
    await skillCard(page, SEEDED_SKILL_NAME).click();

    const dialog = page.getByRole("dialog");
    // Description and content are the two halves of a skill: the description is
    // all the model sees before deciding to open it, the content is what it
    // then loads. Asserting the stored values rather than the fields' presence
    // is what makes this a test of the fetch behind the dialog — the gallery
    // only ever had the summary, so the body proves the detail request landed.
    await expect(dialog.getByLabel("Description", { exact: true })).toHaveValue(
      SEEDED_SKILL_DESCRIPTION,
    );

    // The editor opens on the source: assert the stored text, not the toggle.
    await expect(dialog.getByLabel(/Instructions source/)).toHaveValue(SEEDED_SKILL_CONTENT);
  });

  test("editing a skill warns how far the save reaches", async ({ page }) => {
    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();
    await skillCard(page, SEEDED_SKILL_NAME).click();

    const dialog = page.getByRole("dialog");
    // The editor loads the full skill after the dialog opens; wait for it before
    // counting anything, or an unloaded editor reads as an unprivileged one.
    await expect(dialog.getByLabel("Description", { exact: true })).toHaveValue(
      SEEDED_SKILL_DESCRIPTION,
    );

    const save = dialog.getByRole("button", { name: "Save" });
    await expect(save).toBeVisible();

    // Nothing has changed yet, so there is nothing to warn about. Asserting the
    // absence first is what makes the warning below meaningful — a banner that
    // is always on screen is one nobody reads.
    const blastRadius = dialog.getByRole("alert");
    await expect(blastRadius).toHaveCount(0);

    await dialog.getByLabel("Description", { exact: true }).fill("Edited by the E2E suite.");

    // A skill has no draft and no publish step, so this warning is the only
    // moment anyone is told that the agents following main change too.
    await expect(blastRadius).toContainText("on main");
    await expect(save).toBeEnabled();
  });

  test("a save survives a reload", async ({ page }) => {
    // The warning above is a promise about what a save does; this is the save.
    // On a skill of its own, created and removed here, so it can run beside the
    // specs above without either of them editing the other's row.
    const name = `e2e-scratch-${Date.now().toString(36)}`;
    const edited = "Rewritten, and expected to stay that way.";

    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();

    await page.getByRole("button", { name: "New skill" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill(name);
    await dialog.getByLabel("Description", { exact: true }).fill("Written by the E2E suite.");
    await submitDialog(page, {
      dialog,
      submit: dialog.getByRole("button", { name: "Create" }),
      path: "/api/skills",
    });
    await expect(skillCard(page, name)).toBeVisible();

    await skillCard(page, name).click();
    await expect(dialog.getByLabel("Description", { exact: true })).toHaveValue(
      "Written by the E2E suite.",
    );
    await dialog.getByLabel("Description", { exact: true }).fill(edited);
    await dialog.getByRole("button", { name: "Save" }).click();
    // A changed text asks before it goes live, naming the agents it would reach.
    await page.getByRole("button", { name: "Save now" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // Reloaded rather than read off the cache the mutation patched: a panel that
    // only looks right until the next fetch is a panel that never wrote
    // anything.
    await page.reload();
    await skillCard(page, name).click();
    await expect(dialog.getByLabel("Description", { exact: true })).toHaveValue(edited);

    await dialog.getByRole("button", { name: `More actions for ${name}`, exact: true }).click();
    await page.getByRole("menuitem", { name: `Delete ${name}`, exact: true }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(pageHeading(page, "Skills")).toBeVisible();
    await expect(skillCard(page, name)).toHaveCount(0);
  });
});
