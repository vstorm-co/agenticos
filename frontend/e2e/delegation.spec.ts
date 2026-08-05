import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, openBuilderTab, pageHeading } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * One agent handing work to another, and both of them accounted for.
 *
 * `journey.spec.ts` proves a single agent reaches a model and is billed for it.
 * This is the seam that only exists when there are two: a delegate pinned at a
 * version inside the parent's published spec, the parent's model calling for it
 * mid-turn, the delegate's own answer arriving in a panel of its own, and a
 * second run row attributed to the delegate rather than to whoever asked.
 *
 * **Every assertion here is on something only working delegation can produce**,
 * because this product's pages render their empty state when a query fails and a
 * spec that asserts on a panel, a heading or a count passes against a feature
 * that was never wired up. Concretely:
 *
 * - the delegate's row in the Builder carries its *pin* (`v1, current`), which
 *   needs the delegate's version history to have been read - "No delegates yet"
 *   and "the versions request answered 502" are otherwise the same panel;
 * - the nested panel is found by the **delegate's own handle** and asserted to
 *   report an outcome, not merely to exist;
 * - what is read inside it is a token that appears in exactly one place in this
 *   deployment: the *delegate's* published instructions. The parent cannot say it,
 *   the stub model cannot invent it, and it only arrives if the pinned version was
 *   resolved, built and run;
 * - the delegate's own run history goes from empty to one row **across this one
 *   turn**, which is what separates real delegation from a parent that answered
 *   by itself and a panel drawn from frames nobody metered.
 *
 * The model that answers is `e2e/stub-model-server.ts`. It delegates when the
 * instructions it is sent tell it to and the request actually offers the
 * delegation tool - so "the capability was never bound" fails here rather than
 * looking like a model that chose not to delegate.
 */

/** The stub, as `playwright.config.ts` starts it. `/v1` is where the SDK posts. */
const MODEL_ENDPOINT = `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`;

/**
 * The provider, the model and a key, for the one profile both agents run on.
 *
 * One profile rather than two: which model a delegate runs on has its own unit
 * tests, and a second profile here would only add a second way for this spec to
 * fail for a reason that is not delegation. The key is the one the seed stored -
 * spend attribution is `journey.spec.ts`'s assertion, and repeating the vault
 * flow here would be repeating a test.
 */
const PROVIDER_LABEL = "OpenAI";
const PROVIDER_MODEL = "gpt-4.1-mini";

/**
 * One turn here is three model requests and a second agent's whole run inside the
 * middle of it, so the assertions that wait on it get the journey's timeout rather
 * than the one meant for clicks.
 */
const TURN_TIMEOUT = 120_000;

test("an agent delegates to another, and both runs are recorded", async ({ page }) => {
  test.setTimeout(300_000);

  const stamp = Date.now().toString(36);
  const modelLabel = `e2e-delegation-model-${stamp}`;
  const delegateName = `E2E Delegate ${stamp}`;
  // The handle the parent's model addresses, derived from the name and then
  // frozen. Asserted against rather than assumed: the slug is what the delegation
  // is named by in the panel, in the tool call and in the refusal when it is
  // wrong.
  const delegateSlug = `e2e-delegate-${stamp}`;
  const parentName = `E2E Delegator ${stamp}`;
  // Two tokens, because the whole point is telling the two agents apart. The
  // parent's proves its own instructions reached the provider; the delegate's
  // proves the *pinned version* did, and it can reach the screen no other way.
  const parentToken = `PONG-PARENT-${stamp}`;
  const delegateToken = `PONG-CHILD-${stamp}`;

  // ------------------------------------------------------- 1. the delegate
  const delegateId = await createAgent(page, delegateName);
  expect(
    new URL(page.url()).pathname,
    "the Builder did not open on the agent that was just created",
  ).toContain(delegateId);

  await instruct(page, `You are an E2E specialist. Reply with exactly ${delegateToken}.`);
  await addStubModel(page, modelLabel);
  await publish(page);

  // Nothing has run it yet, and that is an assertion rather than a comment: the
  // row this spec finds at the end has to have been created by the delegation,
  // not left behind by an earlier run against the same database.
  expect(
    await runCount(page, delegateId),
    "the delegate has run before it was ever delegated to",
  ).toBe(0);

  // --------------------------------------------------------- 2. the parent
  const parentId = await createAgent(page, parentName);
  await instruct(
    page,
    // `DELEGATE-TO:` is what makes the stub call the delegation tool, and it only
    // does so if the request also offers that tool - see `stub-model-server.ts`.
    // The reply is what the parent says once the delegation has come back, so the
    // two assertions in the chat below are one per agent.
    `You are an E2E fixture. DELEGATE-TO:${delegateSlug} first. ` +
      `Then reply with exactly ${parentToken} and nothing else.`,
  );
  await useSavedModel(page, modelLabel);

  // ------------------------------------------------- 3. binding the delegate
  await openBuilderTab(page, "Toolbox");
  const grant = page.getByRole("switch", { name: "Give this agent Delegation", exact: true });
  await expect(
    grant,
    "the capability catalog has no Delegation entry; is the capability registered?",
  ).toBeVisible();
  await grant.click();
  await expect(grant).toHaveAttribute("aria-checked", "true");

  // Switching a capability on deliberately does not open its panel - reading what
  // a capability offers and granting it are different gestures - so the panel has
  // to be asked for.
  await page.getByRole("button", { name: /^Delegation\b/ }).click();
  await page.getByRole("button", { name: "Add a delegate" }).click();
  await page.getByRole("menuitem", { name: new RegExp(delegateName) }).click();

  // The row, by the handle it is labelled with. What is asserted on it is the
  // *pin*: a version number and the word "current" can only be printed once the
  // delegate's own version history has been read and compared against the id that
  // was just recorded, so this fails on a pin that silently did not happen where
  // "the delegate is listed" would not.
  const row = page.getByRole("listitem", { name: delegateSlug });
  await expect(row).toBeVisible();
  await expect(row).toContainText(delegateName);
  await expect(
    row,
    "the delegate is listed but carries no pin, so nothing froze it at a version",
  ).toContainText(/v\d+, current/);

  await publish(page);

  // ------------------------------------------------------- 4. running it
  await page.getByRole("button", { name: "Open in chat" }).click();
  await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });
  await expect(page.getByRole("button", { name: /^Agent:/ })).toContainText(parentName);

  // "Live" is the websocket being up rather than the page having rendered.
  await expect(page.getByText("Live")).toBeVisible({ timeout: 30_000 });
  const composer = page.getByRole("textbox", { name: "Type a message..." });
  await expect(composer).toBeEnabled();
  await composer.fill("Do the thing that needs the specialist.");
  await page.getByRole("button", { name: "Send message" }).click();
  // The composer clears on send, so nothing asserted below can be the text that
  // was typed into it.
  await expect(composer).toHaveValue("");

  // ---------------------------------------------- 5. the nested panel
  // Found by the delegate's handle, which the platform put there: the panel is
  // built from `subagent_start`, whose `subagent` is the name the parent's spec
  // pinned. A panel with a name in it is a delegation that was resolved, begun
  // and streamed.
  const panel = page.getByRole("button", { name: new RegExp(`^${delegateSlug}\\b`) });
  await expect(panel, "no delegation panel named the delegate").toBeVisible({
    timeout: TURN_TIMEOUT,
  });
  // An outcome, not a spinner. A delegation that never reported would sit on
  // "working…" forever, which is what the panel looked like before the recording
  // path existed.
  await expect(panel).toContainText("finished", { timeout: TURN_TIMEOUT });

  // The parent's own answer, which arrives after the delegation it waited on.
  await expect(page.getByRole("main").getByText(parentToken)).toBeVisible({
    timeout: TURN_TIMEOUT,
  });

  // The panel closes itself once the delegation is over, so what it holds is one
  // click away - and what it holds is the load-bearing assertion of this spec.
  // `delegateToken` is written in exactly one place in this deployment: the
  // instructions of the version that was pinned. The parent's model never sees
  // it, the stub cannot invent it, and it reaches this page only if the pin was
  // resolved to a spec, built into an agent, run, and streamed back under this
  // delegation's own task id.
  await panel.click();
  await expect(
    page.getByText(delegateToken),
    "the panel is open but holds nothing the delegate generated",
  ).toBeVisible();

  // ------------------------------------------- 6. two runs, attributed apart
  // The delegate's history, which was empty before this turn. One row on it is a
  // run row created for the delegate's *own* agent id - the fact that separates
  // real delegation from a parent that did the work and narrated it.
  await page.goto(`/runs?agent=${delegateId}`);
  await expect(pageHeading(page, "Activity")).toBeVisible();
  await page.getByRole("tab", { name: "Runs", exact: true }).click();
  const delegateRuns = page.getByRole("row").filter({ hasText: modelLabel });
  await expect(
    delegateRuns,
    "the delegate answered but has no run of its own; the delegation was not recorded",
  ).toHaveCount(1);
  // Metered, which is the part a row's existence does not prove. The delegation's
  // share of the run is measured as what the shared ledger grew by while it ran,
  // so a token count of zero here is the whole recording path having written a row
  // and measured nothing - and it would still read as a finished delegation
  // everywhere else. The cost beside it is deliberately only checked for shape: a
  // delegation this small prices to $0.0000, so the number says the cell rendered
  // rather than that money was counted.
  const delegateRun = delegateRuns.first();
  await expect(
    delegateRun.getByRole("cell").nth(3),
    "the delegate's run was recorded with no tokens against it",
  ).toHaveText(/^[1-9]\d*$/);
  await expect(delegateRun.getByRole("cell").nth(4)).toContainText(/^\$\d+\.\d{4}/);

  // And the parent's, which is the other one of the two. Read the same way, from
  // the same page, so a change that merged the two histories fails here.
  await page.goto(`/runs?agent=${parentId}`);
  await page.getByRole("tab", { name: "Runs", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: modelLabel })).toHaveCount(1);

  // ----------------------------------------------------------- 7. cleaning up
  // Through the API, in dependency order - the parent pins the delegate, both
  // name the profile - because this spec runs on every push and an organization
  // that grows two agents and a model per run stops resembling the seed the other
  // specs assert against. Deleting has its own specs; three confirm dialogs here
  // would only add ways to fail at teardown.
  for (const path of [
    `/api/agents/${parentId}`,
    `/api/agents/${delegateId}`,
    `/api/providers/model-profiles/${await profileId(page, modelLabel)}`,
  ]) {
    const removed = await page.request.delete(path);
    expect(removed.ok(), `${path} answered ${removed.status()} at teardown`).toBe(true);
  }
});

/**
 * Create an agent and return its id, landing in the Builder as the product does.
 *
 * The id comes off the URL rather than out of a list: it is what every later step
 * addresses the agent by, and reading it from the page proves creating one
 * actually navigated somewhere.
 */
async function createAgent(page: Page, name: string): Promise<string> {
  await page.goto("/agents");
  await expect(pageHeading(page, "Agents")).toBeVisible();
  // Waited for before the button is used: an agent list that has not arrived yet
  // is not an organization with no agents, and a click into a skeleton fails
  // describing the wrong thing.
  await expect(page.getByRole("button", { name: "New agent" })).toBeEnabled();

  await page.getByRole("button", { name: "New agent" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page).toHaveURL(/\/agents\/[^/?]+/);
  await expect(pageHeading(page, new RegExp(name))).toBeVisible();
  return new URL(page.url()).pathname.split("/").pop() ?? "";
}

/** Write the agent's instructions, in the Builder's own first field. */
async function instruct(page: Page, instructions: string): Promise<void> {
  await page
    .getByRole("tabpanel")
    .getByPlaceholder(/^You are Support Copilot/)
    .fill(instructions);
}

/**
 * Create the model profile both agents run on, pointed at the stub.
 *
 * The endpoint is the whole reason this suite can run an agent at all: model
 * profiles allow a loopback address deliberately, because a local model is a
 * first-class provider here.
 */
async function addStubModel(page: Page, label: string): Promise<void> {
  await page.locator("#add-model-provider").click();
  await page.getByRole("option", { name: PROVIDER_LABEL, exact: true }).click();
  await page.locator("#add-model-id").click();
  await page.getByPlaceholder("Search models…").fill(PROVIDER_MODEL);
  await page.getByRole("option", { name: new RegExp(`^(Use )?${PROVIDER_MODEL}\\b`) }).click();

  // The key picker only appears once a provider has more than one key stored -
  // with exactly one there is nothing to decide. Whichever it lands on is the
  // seed's, and no request is authenticated: the stub does not check.
  const keyPicker = page.locator("#add-model-key");
  if (await keyPicker.isVisible()) {
    await keyPicker.click();
    await page.getByRole("option").first().click();
  }

  await page.locator("#add-model-endpoint").fill(MODEL_ENDPOINT);
  await page.getByRole("button", { name: "Name it something else" }).click();
  await page.locator("#add-model-label").fill(label);
  await page.getByRole("button", { name: "Add model" }).click();

  await expectModel(page, label);
}

/**
 * Point this agent at a profile that already exists.
 *
 * Behind a disclosure, because the Builder puts the decision - provider, model,
 * key - before the named profile that falls out of it. The delegate created the
 * profile; the parent has to choose it, and an agent left on the organization's
 * default would answer from a model this spec knows nothing about.
 */
async function useSavedModel(page: Page, label: string): Promise<void> {
  await page.getByText(/^Use a saved model \(\d+\)/).click();
  await page.getByRole("radio", { name: label, exact: true }).click();
  await expectModel(page, label);
}

/**
 * Assert the agent is on `label`, read off the summary rather than the list.
 *
 * The summary renders only for an id that resolved to one of the organization's
 * profiles, which is the fact the run depends on; a selected row in the list
 * would only say the click landed.
 */
async function expectModel(page: Page, label: string): Promise<void> {
  await expect(page.getByRole("group", { name: "Current model" }).getByText(label)).toBeVisible();
}

/**
 * Publish the draft on screen, and fail on the refusal rather than on its
 * consequence.
 *
 * Publishing validates first, so this is also where a spec the API will not
 * accept is caught - including a delegate the publisher may not run, which is the
 * refusal this whole capability is gated on. Without the second assertion that
 * arrives later as a chat that never answers.
 */
async function publish(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("This agent cannot be published yet")).toHaveCount(0);
  await expect(pageHeading(page)).toContainText("published", { timeout: 30_000 });
}

/**
 * How many runs one agent has, asked of the API.
 *
 * A precondition rather than an assertion about a page, and the honest way to get
 * one: the run table is paginated and shared by every agent in the organization,
 * so counting rows on screen would answer a different question.
 */
async function runCount(page: Page, agentId: string): Promise<number> {
  const response = await page.request.get("/api/runs", { params: { agent_id: agentId } });
  expect(response.ok(), `/api/runs answered ${response.status()}`).toBe(true);
  return ((await response.json()) as { total: number }).total;
}

/** The id of the profile this spec created, which is on no page - it is a uuid. */
async function profileId(page: Page, label: string): Promise<string> {
  const response = await page.request.get("/api/providers/model-profiles");
  expect(response.ok(), `/api/providers/model-profiles answered ${response.status()}`).toBe(true);
  const { items } = (await response.json()) as { items: { id: string; label: string }[] };
  const found = items.find((item) => item.label === label);
  expect(found, `no model profile is labelled ${label}`).toBeDefined();
  return found!.id;
}
