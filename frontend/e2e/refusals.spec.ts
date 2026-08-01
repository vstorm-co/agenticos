import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  DRAFT_AGENT_NAME,
  FAKE_KEY_LABEL,
  SEEDED_SECRET_NAME,
  expectNoRenderedSecret,
  gotoRoleMatrix,
  openAgent,
  pageHeading,
  scopeInMatrix,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * What the platform refuses to do.
 *
 * These are the tests worth having. A feature that stops working is reported by
 * whoever was using it within the hour; a refusal that stops working is
 * reported by nobody, because a leaked key and a control that should never have
 * been offered both look exactly like the software working.
 */

/**
 * The permission that governs each write control, and the control it governs.
 *
 * Hiding a button is not a security boundary — the server refuses the call
 * either way. It is an honesty boundary: offering someone a control that will
 * be rejected teaches them the product is broken rather than that they lack
 * access.
 */
const GOVERNED: { permission: string; path: string; heading: string; control: string }[] = [
  { permission: "agents:edit", path: "/agents", heading: "Agents", control: "New agent" },
  { permission: "skills:edit", path: "/skills", heading: "Skills", control: "New skill" },
  // `secrets:edit`, not `connections:manage`: a Member holds the first at OWN
  // scope, and gating the button on the second made the vault read-only for
  // exactly the people who store their own keys.
  { permission: "secrets:edit", path: "/vault", heading: "Vault", control: "Add key" },
];

test.describe("Refusals", () => {
  test("no stored value, in any form, reaches the vault", async ({ page }) => {
    await page.goto("/vault");
    await expect(pageHeading(page, "Vault")).toBeVisible();

    // Both halves of the vault hold something in this organization —
    // `seed.setup.ts` stores a provider credential and a secret — so the sweeps
    // below are over a page that has something to leak. Sweeping a page whose
    // lists failed to load proves nothing.
    await expect(page.getByRole("main").getByText(FAKE_KEY_LABEL).first()).toBeVisible();
    await expect(page.getByRole("main").getByText(SEEDED_SECRET_NAME).first()).toBeVisible();

    // The page promises that nothing here "can be read back: not through the
    // API, not here". The credential list, the secret list, the model rows and
    // the serialized server payload are each a place that promise could quietly
    // stop being true.
    await expectNoRenderedSecret(page);

    await page.getByRole("button", { name: "Add key" }).first().click();
    await expectNoRenderedSecret(page);
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // Rotation is the one dialog opened against an existing row, so it is the
    // one with a stored value in reach. It prints four characters of it and
    // must print nothing more.
    await page.getByRole("button", { name: `Rotate ${SEEDED_SECRET_NAME}` }).click();
    await expectNoRenderedSecret(page);
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("a list of keys, enumerated so one can be picked, prints none of them", async ({ page }) => {
    // The single most likely place for a key to be printed in full by accident:
    // a control whose whole job is to enumerate the stored ones. It is in the
    // Builder rather than the vault now - a key is chosen where a model is
    // created - and the list is scoped to the provider, so the seeded key only
    // appears once one is named.
    await openAgent(page, DRAFT_AGENT_NAME);

    await page.locator("#add-model-provider").click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();

    await page.locator("#add-model-key").click();
    await expect(page.getByRole("option", { name: new RegExp(FAKE_KEY_LABEL) })).toBeVisible();
    await expectNoRenderedSecret(page);
  });

  test("the UI never offers a write the role catalog denies", async ({ page }) => {
    await gotoRoleMatrix(page);

    const summary = await page.getByText("Your role here is").first().innerText();
    const role = /Your role here is\s+([A-Za-z_]+)/.exec(summary)?.[1] ?? "";
    expect(role, "this user holds no role in this organization").not.toBe("");

    /*
     * A platform superadmin is permitted everything regardless of the role they
     * hold here, so the catalog predicts nothing about what their UI shows —
     * but "everything" is itself a checkable expectation, and it is the one
     * that applies to the seeded owner: the backend makes the first registered
     * user an app admin, and bootstrap's owner is always that user. This used
     * to `test.skip` on exactly that case, which meant the check ran in no
     * environment anybody actually seeds.
     */
    const superadmin = summary.includes("platform superadmin");

    // Read every scope while the matrix is on screen, so the checks below are
    // one navigation each instead of a walk back and forth.
    const expected = new Map<string, boolean>();
    for (const { permission } of GOVERNED) {
      const scope = await scopeInMatrix(page, role, permission);
      // "—" is the catalog saying no; null means this server does not define the
      // permission at all, and inventing an expectation for it would be a guess.
      if (scope !== null) expected.set(permission, scope !== "—");
    }
    expect(
      expected.size,
      "the role matrix listed none of the permissions it governs",
    ).toBeGreaterThan(0);

    for (const { permission, path, heading, control } of GOVERNED) {
      const granted = superadmin ? true : expected.get(permission);
      if (granted === undefined) continue;

      await page.goto(path);
      await expect(pageHeading(page, heading)).toBeVisible();

      const button = page.getByRole("button", { name: control }).first();
      if (granted) {
        await expect(
          button,
          superadmin
            ? `a platform superadmin is permitted everything, so "${control}" must be offered`
            : `${role} holds ${permission}, so "${control}" must be offered`,
        ).toBeVisible();
      } else {
        await expect(
          page.getByRole("button", { name: control }),
          `${role} does not hold ${permission}, so "${control}" must not be offered`,
        ).toHaveCount(0);
      }
    }
  });
});
