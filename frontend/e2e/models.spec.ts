import { expect, test } from "./fixtures";
import type { Locator, Page } from "@playwright/test";

import {
  AUTH_STATE,
  DRAFT_AGENT_NAME,
  SEEDED_MODEL_ID,
  SEEDED_MODEL_LABEL,
  expectNoRenderedSecret,
  openAgent,
  saveDraft,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Which model an agent runs on, from the Builder.
 *
 * This used to be part of `vault.spec.ts`, because models were listed on the
 * vault page beside the keys. They are not any more, and the move was the point:
 * a model profile is provider + model id + which key, and the moment somebody is
 * choosing one they are choosing what an agent runs on — a Builder decision. The
 * vault kept the half it owns, which is the key.
 *
 * What is asserted here is only what a unit test cannot reach.
 * `add-model.integration.test.tsx` already drives this form against a mocked
 * API; what it cannot do is open a Radix select, and it cannot know what the
 * real provider catalog says about which providers accept an endpoint and which
 * can run without a key. Both of those decide every field below them.
 *
 * The draft agent is the subject rather than the seeded one: these specs select
 * a model, the Builder autosaves, and pointing the published agent's draft at a
 * profile this file then deletes would leave the rest of the suite with an agent
 * that cannot be published.
 */
test.describe("Models", () => {
  test("names the provider and the model id of what the agent runs on", async ({ page }) => {
    // A label is worth nothing on its own: `openai · gpt-4.1` is the pair that
    // decides which API is called and what the run costs, and it is the pair
    // somebody opens this panel to check.
    await openAgent(page, DRAFT_AGENT_NAME);
    await selectSavedModel(page, SEEDED_MODEL_LABEL);

    const current = page.getByRole("group", { name: "Current model" });
    await expect(current).toContainText(SEEDED_MODEL_LABEL);
    await expect(current).toContainText(`openai · ${SEEDED_MODEL_ID}`);
  });

  test("a model cannot be added without a provider and a model id", async ({ page }) => {
    await openAgent(page, DRAFT_AGENT_NAME);

    const submit = page.getByRole("button", { name: "Add model" });
    await expect(submit).toBeDisabled();

    // Nothing is preselected, and the model field is not even usable yet: which
    // models exist is a question only the provider can answer.
    await expect(page.locator("#add-model-id")).toBeDisabled();

    await pickProvider(page, "OpenAI");
    // Still refused. A profile with a provider and no model id is one that fails
    // at the moment a run needs it rather than here.
    await expect(submit).toBeDisabled();

    await pickModel(page, "gpt-4.1-mini");
    await expect(submit).toBeEnabled();
  });

  test("a self-hosted model needs its endpoint, and then needs no key", async ({ page }) => {
    const label = `e2e-keyless-${Date.now().toString(36)}`;

    await openAgent(page, DRAFT_AGENT_NAME);

    // Ollama on a machine of your own has nothing to authenticate against, and
    // demanding a key here is demanding that somebody invent one.
    await pickProvider(page, "Ollama");
    await pickModel(page, "llama3.2");

    const submit = page.getByRole("button", { name: "Add model" });
    // Refused until it says where to reach the server. `keyless` alone does not
    // make a profile runnable — it is true of `openai` too, because
    // OpenAI-compatible servers speak its API — so the endpoint is what
    // separates a deliberate local model from a profile whose key was deleted.
    await expect(submit).toBeDisabled();

    await nameIt(page, label);
    await page.locator("#add-model-endpoint").fill("https://example.com/v1");
    await expect(submit).toBeEnabled();
    await submit.click();

    // Selected, not merely created: somebody who came here to choose a model has
    // chosen one, and an agent left on the old value would make the work look
    // like it did not take.
    const current = page.getByRole("group", { name: "Current model" });
    await expect(current).toContainText(label);
    await expect(current).toContainText("ollama · llama3.2");
    // The badge that decides whether the agent can run at all. On a self-hosted
    // profile it is the expected state rather than a warning - but it is also
    // the refusal half of this surface, and the only place it is asserted: the
    // platform says up front what it will not be able to do, instead of finding
    // out at the first run. It used to be checked on the vault page against
    // bootstrap's own profile, which has a key whenever a deployment is
    // bootstrapped with one - so it was asserting the seed rather than the badge.
    await expect(current.getByText("no key")).toBeVisible();

    // Saved before the reload rather than waited out: the Builder stores the
    // draft 1.2s after the last edit, and a reload that beats the timer reloads
    // the *previous* model - which reads exactly like a create that never took.
    await saveDraft(page);

    // Reloaded, because a row that exists only in the mutation's cache patch is
    // a row that was never written.
    await page.reload();
    await expect(page.getByRole("group", { name: "Current model" })).toContainText(label);
    await expectNoRenderedSecret(page);

    // Put the agent back on the seeded model before the profile it points at is
    // deleted, in that order: the reverse leaves a draft naming a profile this
    // organization no longer has.
    await selectSavedModel(page, SEEDED_MODEL_LABEL);
    await savedModels(page)
      .getByRole("button", { name: `Remove ${label}` })
      .click();
    await expect(savedModels(page).getByRole("radio", { name: label })).toHaveCount(0);
  });

  test("a refused endpoint comes back in the server's own words", async ({ page }) => {
    // Every `base_url` check reports the URL it refused, and this is the whole
    // journey for one of them: the browser sends it, the service refuses it, the
    // proxy carries the refusal back with its body intact, and the form prints
    // the sentence rather than handing it to a toast that takes it away again.
    //
    // The scheme check rather than the internal-address one, because it applies
    // either way: whether a private address is refused depends on
    // ALLOW_INTERNAL_MODEL_ENDPOINTS, and a spec that fails on a legitimate
    // configuration is a spec people learn to re-run instead of read. That
    // message — the one naming the setting — is asserted in the unit tests.
    await openAgent(page, DRAFT_AGENT_NAME);

    await pickProvider(page, "Ollama");
    await pickModel(page, "llama3.2");
    await nameIt(page, `e2e-refused-${Date.now().toString(36)}`);

    const endpoint = page.locator("#add-model-endpoint");
    await endpoint.fill("file:///etc/passwd");
    await page.getByRole("button", { name: "Add model" }).click();

    await expect(page.getByText(/must be an http or https URL/)).toBeVisible();
    // And what was typed is still there. A form that cleared itself on a refusal
    // would throw away the thing that needs correcting.
    await expect(endpoint).toHaveValue("file:///etc/passwd");
  });
});

/** The disclosure holding the profiles this organization has already named. */
function savedModels(page: Page): Locator {
  return page.getByRole("radiogroup", { name: "Model" });
}

/**
 * Point the agent at a profile that already exists.
 *
 * Behind a disclosure on purpose — the panel leads with the form, because
 * choosing a model *is* choosing a provider, a model id and a key, and a list of
 * profiles somebody else created is not where that decision starts. `<details>`
 * has no ARIA role to aim at, so the summary is clicked by its own text, and
 * only when it is still shut: clicking it twice closes it again.
 */
async function selectSavedModel(page: Page, label: string): Promise<void> {
  const list = savedModels(page);
  const radio = list.getByRole("radio", { name: label, exact: true });
  if (!(await radio.isVisible())) {
    await page.getByText(/^Use a saved model \(\d+\)$/).click();
  }
  await expect(radio).toBeVisible();
  if ((await radio.getAttribute("aria-checked")) !== "true") await radio.click();
  await expect(radio).toHaveAttribute("aria-checked", "true");
}

/** Choose a provider, which is what decides every field below it. */
async function pickProvider(page: Page, label: string): Promise<void> {
  await page.locator("#add-model-provider").click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

/**
 * Put a model id in, through the catalog rather than past it.
 *
 * The control is a combobox over what the provider publishes, and anything typed
 * that the catalog does not have is offered as itself — which is the free-text
 * case the field exists for, since providers ship models faster than any list
 * here is refreshed.
 */
async function pickModel(page: Page, model: string): Promise<void> {
  await page.locator("#add-model-id").click();
  await page.getByPlaceholder("Search models…").fill(model);
  await page.getByRole("option", { name: new RegExp(`^(Use )?${model}\\b`) }).click();
  await expect(page.locator("#add-model-id")).toContainText(model);
}

/**
 * Name the profile something other than the derived `Provider · model`.
 *
 * Behind a disclosure, because the derived name is right almost always; it
 * exists so an organization can run the same model twice under two keys and tell
 * them apart. Here it is what lets a spec find the row it just created.
 */
async function nameIt(page: Page, label: string): Promise<void> {
  await page.getByRole("button", { name: "Name it something else" }).click();
  await page.locator("#add-model-label").fill(label);
}
