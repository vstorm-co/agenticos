import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  SEEDED_SKILL_CONTENT,
  SEEDED_SKILL_DESCRIPTION,
  SEEDED_SKILL_NAME,
  pageHeading,
  skillCard,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Skills are the one thing on this platform that has no draft and no publish
 * step: a save is live everywhere on the next run. The gallery has to list what
 * exists, the editor has to open it with what is actually stored, and the
 * editor has to say out loud how far a save reaches.
 *
 * `seed.setup.ts` writes the skill these assert on, through this same UI —
 * bootstrap creates none, and a gallery asserted to be empty is a gallery that
 * passes just as happily when the request behind it 502s.
 */

test.describe("Skills", () => {
  test("the gallery lists the organization's skills", async ({ page }) => {
    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();

    const card = skillCard(page, SEEDED_SKILL_NAME);
    await expect(card).toBeVisible();
    // The description is on the card because it is the only part the model sees
    // before deciding whether to open the skill — content, not decoration.
    await expect(card).toContainText(SEEDED_SKILL_DESCRIPTION);
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
    await expect(dialog.getByLabel("Description")).toHaveValue(SEEDED_SKILL_DESCRIPTION);
    await expect(dialog.getByLabel("Content")).toHaveValue(SEEDED_SKILL_CONTENT);
  });

  test("editing a skill warns how far the save reaches", async ({ page }) => {
    await page.goto("/skills");
    await expect(pageHeading(page, "Skills")).toBeVisible();
    await skillCard(page, SEEDED_SKILL_NAME).click();

    const dialog = page.getByRole("dialog");
    // The editor loads the full skill after the dialog opens; wait for it before
    // counting anything, or an unloaded editor reads as an unprivileged one.
    await expect(dialog.getByLabel("Description")).toHaveValue(SEEDED_SKILL_DESCRIPTION);

    const save = dialog.getByRole("button", { name: "Save" });
    await expect(save).toBeVisible();

    // Nothing has changed yet, so there is nothing to warn about. Asserting the
    // absence first is what makes the warning below meaningful — a banner that
    // is always on screen is one nobody reads.
    const blastRadius = dialog.getByRole("alert");
    await expect(blastRadius).toHaveCount(0);

    await dialog.getByLabel("Description").fill("Edited by the E2E suite.");

    // A skill has no draft and no publish step, so this warning is the only
    // moment anyone is told that every agent bound to the skill changes too.
    await expect(blastRadius).toContainText("Saving reaches every agent bound to this skill");
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
    await dialog.getByLabel("Description").fill("Written by the E2E suite.");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(skillCard(page, name)).toBeVisible();

    await skillCard(page, name).click();
    await expect(dialog.getByLabel("Description")).toHaveValue("Written by the E2E suite.");
    await dialog.getByLabel("Description").fill(edited);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();

    // Reloaded rather than read off the cache the mutation patched: a panel that
    // only looks right until the next fetch is a panel that never wrote
    // anything.
    await page.reload();
    await expect(skillCard(page, name)).toContainText(edited);

    await page.getByRole("button", { name: `Delete ${name}` }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(skillCard(page, name)).toHaveCount(0);
  });
});
