import { expect, test } from "./fixtures";

import { AUTH_STATE, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * One agent, from a provider key to a run with a cost against it.
 *
 * Every other spec checks one page in isolation, which is exactly where a
 * platform like this breaks: each part passes its own tests while the seams
 * between them rot. This is the only test that proves a key stored in Settings
 * is the key a model resolves, that a model chosen in the Builder is the model
 * a run bills against, and that the run the chat started against the agent the
 * Builder published is the run Activity reports.
 *
 * It runs against real infrastructure and spends real money — a few cents of a
 * model call — so it is opt-in through `E2E_PROVIDER_API_KEY`. Each step skips
 * with a reason when its precondition is missing, so the suite stays useful
 * against a partly-seeded environment instead of failing noisily.
 */

/** A real provider key. Without one, every step after the first would be theatre. */
const PROVIDER_KEY = process.env.E2E_PROVIDER_API_KEY ?? "";
/** Provider as it is named in the picker. */
const PROVIDER_LABEL = process.env.E2E_PROVIDER_LABEL ?? "OpenAI";
/** Something small: this journey pays for the tokens it spends. */
const PROVIDER_MODEL = process.env.E2E_PROVIDER_MODEL ?? "gpt-4.1-mini";

test("an agent goes from a provider key to a run with a cost", async ({ page }) => {
  // A model call sits in the middle of this; the default timeout is for clicks.
  test.setTimeout(240_000);

  const stamp = Date.now().toString(36);
  const keyLabel = `e2e-key-${stamp}`;
  const modelLabel = `e2e-model-${stamp}`;
  const agentName = `E2E Journey ${stamp}`;
  const answerToken = `PONG-${stamp}`;

  // ---------------------------------------------------------------- 1. a key
  await page.goto("/vault");
  await expect(pageHeading(page, "Vault")).toBeVisible();

  test.skip(
    PROVIDER_KEY === "",
    "E2E_PROVIDER_API_KEY is not set — a fake key would make every step after this one a lie",
  );

  const addKey = page.getByRole("button", { name: "Add credential" });
  if ((await addKey.count()) === 0) {
    test.skip(true, "this user cannot manage connections, so the journey cannot start");
  }
  await addKey.click();

  const keyDialog = page.getByRole("dialog");
  await keyDialog.getByRole("combobox").first().click();
  await page.getByRole("option", { name: PROVIDER_LABEL, exact: true }).click();
  await keyDialog.getByLabel("Label").fill(keyLabel);
  // Named by the provider's own secret schema, not by this form: every provider
  // whose credential is one token calls that token `api_key`.
  await keyDialog.getByLabel(/Api Key/).fill(PROVIDER_KEY);
  await keyDialog.getByRole("button", { name: "Store credential" }).click();

  // Asserted in the list rather than in the toast: a toast says the request was
  // accepted, the list says the key is actually there. Everything below depends
  // on the second.
  await expect(page.getByRole("main").getByText(keyLabel)).toBeVisible();

  // -------------------------------------------------------------- 2. a model
  await page.getByRole("button", { name: "Add model" }).click();
  const modelDialog = page.getByRole("dialog");
  await modelDialog.getByLabel("Name").fill(modelLabel);
  await modelDialog.getByLabel("Model id").fill(PROVIDER_MODEL);

  // Bind it to the key just stored rather than to the organization default: the
  // point of this journey is that this key resolves for this run.
  await modelDialog.getByRole("combobox").filter({ hasText: "Choose a key" }).click();
  await page.getByRole("option", { name: keyLabel }).click();
  await modelDialog.getByRole("button", { name: "Add model" }).click();

  await expect(page.getByRole("main").getByText(modelLabel)).toBeVisible();

  // ------------------------------------------------------------- 3. an agent
  await page.goto("/agents");
  await expect(pageHeading(page, "Agents")).toBeVisible();

  const newAgent = page.getByRole("button", { name: "New agent" });
  if ((await newAgent.count()) === 0) {
    test.skip(true, "this user cannot create agents");
  }
  await newAgent.click();

  const agentDialog = page.getByRole("dialog");
  await agentDialog.getByLabel("Name").fill(agentName);
  await agentDialog.getByRole("button", { name: "Create", exact: true }).click();

  // Creating navigates straight into the Builder for the new draft.
  await expect(page).toHaveURL(/\/agents\/[^/]+$/);
  await expect(pageHeading(page, new RegExp(agentName))).toBeVisible();

  // ------------------------------------------ 4. instructions, model, capability
  const build = page.getByRole("tabpanel");
  await build
    .getByPlaceholder(/^You are Support Copilot/)
    .fill(`You are an E2E fixture. Reply with exactly ${answerToken} and nothing else.`);

  // The model section leads with the provider/model/key form, because that is
  // how a model is normally chosen. This journey already created one in step 2
  // and needs *that* profile specifically — the whole point is that the key
  // stored in step 1 is the key this run bills against — so it goes through the
  // saved-model disclosure instead.
  await build.getByText(/^Use a saved model/).click();
  await build.getByRole("radio", { name: modelLabel, exact: true }).click();
  // Asserted on the summary rather than on the radio: the summary renders only
  // for an id that resolved to one of the organization's profiles, which is the
  // fact the rest of the journey depends on.
  await expect(
    page.getByRole("group", { name: "Current model" }).getByText(modelLabel),
  ).toBeVisible();

  // Capabilities live in Toolbox, not Build. This used to look for them in the
  // Build panel and find none, so the step below skipped itself with "the
  // capability catalog is empty" against a deployment whose catalog was fine -
  // which is the failure mode a skip-with-a-reason is supposed to prevent.
  await page.getByRole("tab", { name: "Toolbox" }).click();
  const toolbox = page.getByRole("tabpanel");

  // A switch, labelled "Give this agent <name>" in the list on the left.
  const capabilities = toolbox.getByRole("switch", { name: /^Give this agent / });
  if ((await capabilities.count()) === 0) {
    test.skip(true, "the capability catalog is empty in this environment");
  }
  const capability = capabilities.first();
  await capability.click();
  await expect(capability).toHaveAttribute("aria-checked", "true");

  // Configure it. A side-effecting capability parks its first call in the
  // approval queue by default, which would leave the run below waiting on a
  // human forever — so this journey states, deliberately, that it may act
  // unattended. That choice is the configuration being exercised.
  //
  // The panel is rendered for a capability whether or not it is on, with its
  // controls inert until it is - so this runs after the switch above, not
  // before.
  const approval = toolbox.getByLabel("Human approval");
  if (await approval.isVisible()) {
    await approval.click();
    await page.getByRole("option", { name: "Never ask" }).click();
  }

  // ------------------------------------------------------------ 5. publishing
  const publish = page.getByRole("button", { name: "Publish" });
  if ((await publish.count()) === 0) {
    test.skip(true, "this user cannot publish agents");
  }
  await publish.click();

  // Publishing validates the draft first, so this is also the assertion that the
  // spec the Builder wrote is one the API accepts. The status badge lives in the
  // page title, and it is the only thing that unlocks the chat action below.
  await expect(pageHeading(page)).toContainText("published", { timeout: 30_000 });
  await expect(page.getByText("This agent cannot be published yet")).toHaveCount(0);

  // ------------------------------------------------------------ 6. running it
  // The Builder hands the agent to the chat, which is where this product runs
  // one. That the chat is addressed to *this* agent rather than the general
  // assistant is what the next assertion turns on: the assistant would answer
  // the same prompt without the instructions that make the token appear.
  await page.getByRole("button", { name: "Open in chat" }).click();
  await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Chat controls" })).toContainText(agentName);

  // Disabled until the websocket is up; "Live" is the proof it reached the
  // backend rather than merely rendered.
  await expect(page.getByText("Live")).toBeVisible({ timeout: 30_000 });
  const composer = page.getByRole("textbox", { name: "Type a message..." });
  await expect(composer).toBeEnabled();
  await composer.fill("Say the word.");
  await page.getByRole("button", { name: "Send message" }).click();

  // The composer clears on send, so the assertion below can only match the
  // model's answer, never the text that was typed into it.
  await expect(composer).toHaveValue("");
  await expect(page.getByRole("main").getByText(answerToken)).toBeVisible({ timeout: 120_000 });

  // -------------------------------------------------- 7. the run in Activity
  await page.goto("/runs");
  await expect(pageHeading(page, "Activity")).toBeVisible();
  await page.getByRole("tab", { name: "Runs", exact: true }).click();

  // A run records the named model it billed against, which is how the row is
  // found — and a cost, which is the proof that usage was metered rather than
  // merely executed.
  const row = page.getByRole("row").filter({ hasText: modelLabel }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText(/\$\d+\.\d{4}/);
});
