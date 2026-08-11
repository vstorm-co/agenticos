import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_AGENT_HANDLE, agentCard, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * One agent, from a stored key to a run with a cost against it.
 *
 * Every other spec checks one page in isolation, which is exactly where a
 * platform like this breaks: each part passes its own tests while the seams
 * between them rot. This is the only test that proves a key stored in the vault
 * is the key a model resolves, that a model created in the Builder is the model
 * a run bills against, and that the run the chat started against the agent the
 * Builder published is the run Activity reports.
 *
 * The model that answers is `e2e/stub-model-server.ts`, an OpenAI-compatible
 * server Playwright starts beside the app. That is not a compromise for cost -
 * it is what makes this runnable at all. It used to need a real provider key,
 * so it skipped itself in every environment that did not have one, which was
 * every environment including CI: the one test covering the seams was the one
 * test nobody ran.
 *
 * What the stub costs in coverage is worth naming. This no longer proves that
 * OpenAI answers, or that a real key is accepted - those are the provider's
 * business and would make a green suite depend on somebody else's uptime. What
 * it still proves is everything between: the endpoint reaches the resolver, the
 * profile's key is what the run is attributed to, the agent's *instructions*
 * reach the model request (the stub replies with the token they name, and
 * nothing else could put it there), the streaming path carries the answer to the
 * browser, and the usage that came back is metered into a cost.
 */

/** The stub, as `playwright.config.ts` starts it. `/v1` is where the SDK posts. */
const MODEL_ENDPOINT = `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`;

/**
 * Stored, bound and never checked by anything.
 *
 * The stub does not authenticate - see its own docstring for why - but the
 * profile still needs a key, because a key is what spend is attributed to. This
 * journey's last assertion is a cost, and a cost with nothing to bill is not
 * one.
 */
const PROVIDER_KEY = "sk-e2e-stub-not-a-real-key";
/** Provider as it is named in the picker. OpenAI-compatible is what the stub is. */
const PROVIDER_LABEL = "OpenAI";
/** Priced by the bundled snapshot, which is what turns usage into a number. */
const PROVIDER_MODEL = "gpt-4.1-mini";

test("an agent goes from a stored key to a run with a cost", async ({ page }) => {
  // A whole agent run sits in the middle of this; the default timeout is for
  // clicks.
  test.setTimeout(240_000);

  const stamp = Date.now().toString(36);
  const keyLabel = `e2e-key-${stamp}`;
  const modelLabel = `e2e-model-${stamp}`;
  const agentName = `E2E Journey ${stamp}`;
  const answerToken = `PONG-${stamp}`;

  // 1. a key
  await page.goto("/vault");
  await expect(pageHeading(page, "Vault")).toBeVisible();

  // Waited for before it is counted. `count()` does not retry, and the vault
  // draws a skeleton until the key list answers - so a page that had simply not
  // loaded yet read as a user who is not allowed to store keys, and this whole
  // journey skipped itself with the wrong reason.
  await expect(page.getByText(/\d+ keys? stored|1 key stored/)).toBeVisible();
  const addKey = page.getByRole("button", { name: "Add key" }).first();
  if (!(await addKey.isVisible())) {
    test.skip(true, "this user cannot store a key, so the journey cannot start");
  }
  await addKey.click();

  // Two questions rather than one list of thirty-one: which family of service,
  // then which one. The fields below are generated from that service's own
  // secret schema, which is why the provider is chosen before anything is typed.
  const keyDialog = page.getByRole("dialog");
  await keyDialog.getByRole("button", { name: /^Model provider/ }).click();
  await keyDialog.getByLabel(/^(Which one|Service)$/).click();
  await page.getByRole("option", { name: PROVIDER_LABEL, exact: true }).click();
  await keyDialog.getByLabel("Name").fill(keyLabel);
  // Named by the provider's own secret schema, not by this form: every provider
  // whose credential is one token calls that token an API key. Scoped to the
  // textbox because the reveal button beside it is named "Show API key".
  await keyDialog.getByRole("textbox", { name: /API key/i }).fill(PROVIDER_KEY);
  await keyDialog.getByRole("button", { name: "Store secret" }).click();

  // Asserted in the list rather than in the toast: a toast says the request was
  // accepted, the list says the key is actually there. Everything below depends
  // on the second.
  await expect(page.getByRole("main").getByText(keyLabel)).toBeVisible();

  // 2. an agent
  await page.goto("/agents");
  await expect(pageHeading(page, "Agents")).toBeVisible();

  // Waited for, then counted - as at the vault above, and for the same reason:
  // an agent list that has not arrived yet is not a user who may not create one.
  await expect(agentCard(page, SEEDED_AGENT_HANDLE)).toBeVisible();
  const newAgent = page.getByRole("button", { name: "New agent" }).first();
  if (!(await newAgent.isVisible())) {
    test.skip(true, "this user cannot create agents");
  }
  await newAgent.click();

  const agentDialog = page.getByRole("dialog");
  await agentDialog.getByLabel("Name").fill(agentName);
  await agentDialog.getByRole("button", { name: "Create", exact: true }).click();

  // Creating navigates straight into the Builder for the new draft.
  await expect(page).toHaveURL(/\/agents\/[^/]+$/);
  await expect(pageHeading(page, new RegExp(agentName))).toBeVisible();
  const agentId = new URL(page.url()).pathname.split("/").pop() ?? "";

  // 3. instructions and a model
  const build = page.getByRole("tabpanel");
  await build
    .getByPlaceholder(/^You are Support Copilot/)
    .fill(`You are an E2E fixture. Reply with exactly ${answerToken} and nothing else.`);

  // The model is created here rather than on the vault page, because this is
  // where a model is chosen: provider, model id and which key, which is the
  // whole of the decision. The named profile is what falls out of it.
  await page.locator("#add-model-provider").click();
  await page.getByRole("option", { name: PROVIDER_LABEL, exact: true }).click();
  await page.locator("#add-model-id").click();
  await page.getByPlaceholder("Search models…").fill(PROVIDER_MODEL);
  await page.getByRole("option", { name: new RegExp(`^(Use )?${PROVIDER_MODEL}\\b`) }).click();

  // Bound to the key stored in step 1 rather than to whichever one the
  // organization had already: the point of this journey is that *that* key is
  // the one this run bills against. The picker only appears once a provider has
  // more than one key stored for it - with exactly one there is nothing to
  // decide, and the form says which it is using instead.
  const keyPicker = page.locator("#add-model-key");
  if (await keyPicker.isVisible()) {
    await keyPicker.click();
    await page.getByRole("option", { name: new RegExp(keyLabel) }).click();
  }

  // Where the request goes, which is the whole reason this journey can run at
  // all. The field appears for every provider whose SDK names an endpoint
  // parameter, and OpenAI is one - which is also why an OpenAI-compatible stub
  // is a faithful stand-in rather than a special case.
  await page.locator("#add-model-endpoint").fill(MODEL_ENDPOINT);

  await page.getByRole("button", { name: "Name it something else" }).click();
  await page.locator("#add-model-label").fill(modelLabel);
  await page.getByRole("button", { name: "Add model" }).click();

  // Created and selected in one step. Asserted on the summary rather than on the
  // list, because the summary renders only for an id that resolved to one of the
  // organization's profiles - which is the fact the rest of the journey depends
  // on.
  await expect(
    page.getByRole("group", { name: "Current model" }).getByText(modelLabel),
  ).toBeVisible();

  // 4. a capability
  // Capabilities live in Toolbox, not Build. This used to look for them in the
  // Build panel and find none, so the step below skipped itself with "the
  // capability catalog is empty" against a deployment whose catalog was fine -
  // which is the failure mode a skip-with-a-reason is supposed to prevent.
  await page.getByRole("tab", { name: "Toolbox" }).click();
  const toolbox = page.getByRole("tabpanel");

  // A switch, labelled "Give this agent <name>" in the list on the left.
  const capability = toolbox.getByRole("switch", { name: /^Give this agent / }).first();
  if (!(await capability.isVisible())) {
    test.skip(true, "the capability catalog is empty in this environment");
  }
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

  // 5. publishing
  const publish = page.getByRole("button", { name: "Publish" });
  if (!(await publish.isVisible())) {
    test.skip(true, "this user cannot publish agents");
  }
  await publish.click();

  // Publishing validates the draft first, so this is also the assertion that the
  // spec the Builder wrote is one the API accepts. The status badge lives in the
  // page title, and it is the only thing that unlocks the chat action below.
  await expect(pageHeading(page)).toContainText("published", { timeout: 30_000 });
  await expect(page.getByText("This agent cannot be published yet")).toHaveCount(0);

  // 6. running it
  // The Builder hands the agent to the chat, which is where this product runs
  // one. That the chat is addressed to *this* agent rather than the general
  // assistant is what the next assertion turns on: the assistant would answer
  // the same prompt without the instructions that make the token appear.
  await page.getByRole("button", { name: "Open in chat" }).click();
  await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });
  // The agent picker is its own control beside the composer, named after
  // whoever is about to answer.
  await expect(page.getByRole("button", { name: /^Agent:/ })).toContainText(agentName);

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

  // 7. the run in Activity
  await page.goto("/runs");
  await expect(pageHeading(page, "Activity")).toBeVisible();
  await page.getByRole("tab", { name: "Runs", exact: true }).click();

  // A run records the named model it billed against, which is how the row is
  // found — and a cost, which is the proof that usage was metered rather than
  // merely executed.
  const row = page.getByRole("row").filter({ hasText: modelLabel }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText(/\$\d+\.\d{4}/);

  // 8. cleaning up
  // This is the one spec that creates a whole agent, and it runs on every push -
  // so without this the organization grows an agent, a model and a key per run,
  // and the counts other specs take start describing the history of CI rather
  // than the seed.
  //
  // Through the API rather than the UI, and that is the distinction worth
  // keeping: what is asserted above went through the interface, because the
  // interface is what this journey is about. Deleting has its own specs, and
  // driving three confirm dialogs here would only put this test at risk of
  // failing at teardown for reasons nobody is investigating.
  //
  // In dependency order - the agent names the profile, the profile names the
  // key - because the API refuses to orphan either.
  for (const path of [
    `/api/agents/${agentId}`,
    `/api/providers/model-profiles/${await idOf(page, "/api/providers/model-profiles", "label", modelLabel)}`,
    `/api/secrets/${await idOf(page, "/api/secrets", "name", keyLabel)}`,
  ]) {
    const removed = await page.request.delete(path);
    expect(removed.ok(), `${path} answered ${removed.status()} at teardown`).toBe(true);
  }
});

/**
 * The id of the one row in `path` whose `field` reads `value`.
 *
 * Asked of the API rather than read off the page, because none of these ids are
 * on screen - deliberately, they are uuids nobody types - and teardown needs
 * exactly them.
 */
async function idOf(
  page: import("@playwright/test").Page,
  path: string,
  field: "label" | "name",
  value: string,
): Promise<string> {
  const response = await page.request.get(path);
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true);
  const { items } = (await response.json()) as { items: Record<string, string>[] };
  const found = items.find((item) => item[field] === value);
  expect(found, `${path} has no row whose ${field} is ${value}`).toBeDefined();
  return found!["id"]!;
}
