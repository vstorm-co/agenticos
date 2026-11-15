import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  SEEDED_AGENT_HANDLE,
  agentCard,
  nowListed,
  nowMatching,
  pageHeading,
  pageStatus,
  submitDialog,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * One agent, from a stored key to a run with a cost against it.
 *
 * Every other spec checks one page in isolation, which is exactly where a
 * platform like this breaks: each part passes its own tests while the seams
 * between them rot. This is the only test that proves a key stored in the vault
 * is the key a model resolves, that a model created in the Builder is the model
 * a run bills against, that the run the chat started against the agent the
 * Builder published is the run Activity reports, and that a stranger with the
 * hosted link reaches that same frozen version (#517).
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

test("an agent goes from a stored key to a run with a cost", async ({ page, browser }) => {
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
  await expect(pageHeading(page, "Vault"), "the vault page never drew its heading").toBeVisible();

  // Empty lists deliberately hide their toolbar. Check the real resource
  // response instead of treating the hidden zero-count as an unloaded page.
  const keys = await page.request.get("/api/secrets");
  expect(keys.ok(), "the vault resource failed to load").toBe(true);
  const addKey = page.getByRole("button", { name: "Add key" }).first();
  await expect(addKey, "the owner must be able to store a key").toBeVisible();
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
  await keyDialog.getByRole("button", { name: "Store key" }).click();

  // Asserted in the list rather than in the toast: a toast says the request was
  // accepted, the list says the key is actually there. Everything below depends
  // on the second.
  await nowListed(page.request, "/api/secrets", "name", keyLabel);
  await expect(
    page.getByRole("main").getByText(keyLabel),
    `the API lists the key ${keyLabel}, but the vault page does not show it`,
  ).toBeVisible();

  // 2. an agent
  await page.goto("/agents");
  await expect(pageHeading(page, "Agents"), "the agents page never drew its heading").toBeVisible();

  // Waited for, then counted - as at the vault above, and for the same reason:
  // an agent list that has not arrived yet is not a user who may not create one.
  await expect(
    agentCard(page, SEEDED_AGENT_HANDLE),
    `the seeded agent ${SEEDED_AGENT_HANDLE} is not on the page, so the list had not arrived`,
  ).toBeVisible();
  const newAgent = page.getByRole("button", { name: "New agent" }).first();
  await expect(newAgent, "the owner must be able to create agents").toBeVisible();
  await newAgent.click();

  const agentDialog = page.getByRole("dialog");
  await agentDialog.getByLabel("Name").fill(agentName);
  await agentDialog.getByRole("button", { name: "Create", exact: true }).click();

  // Creating navigates straight into the Builder for the new draft.
  await expect(page).toHaveURL(/\/agents\/[^/]+$/);
  await expect(
    pageHeading(page, new RegExp(agentName)),
    `creating ${agentName} navigated, but the Builder never drew its name`,
  ).toBeVisible();
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
    `the model ${modelLabel} was added, but the Current model summary does not name it - ` +
      "which means the id it was created with resolved to no profile of this organization",
  ).toBeVisible();

  // 4. a capability
  // Capabilities live in Toolbox, not Build. This used to look for them in the
  // Build panel and find none, so the step below skipped itself with "the
  // capability catalog is empty" against a deployment whose catalog was fine -
  // which is the failure mode a skip-with-a-reason is supposed to prevent.
  await page.getByRole("tab", { name: "Toolbox" }).click();
  const toolbox = page.getByRole("tabpanel");

  // A switch, labelled "Give this agent <name>" on the capability's card. A new
  // agent starts with the recommended capabilities on; Calculations is not among
  // them - the starter does its sums in its workspace - so it is switched on here.
  const capability = toolbox.getByRole("switch", { name: "Give this agent Calculations" });
  await expect(capability, "the capability catalog must include Calculations").toBeVisible();
  await expect(capability).toHaveAttribute("aria-checked", "false");
  await capability.click();
  await expect(capability).toHaveAttribute("aria-checked", "true");
  await toolbox.getByRole("button", { name: "Calculations settings", exact: true }).click();
  // The settings open in a sheet beside the page, outside the tab panel.
  const settings = page.getByRole("dialog");

  // Configure it. A side-effecting capability parks its first call in the
  // approval queue by default, which would leave the run below waiting on a
  // human forever — so this journey states, deliberately, that it may act
  // unattended. That choice is the configuration being exercised.
  //
  // The panel is rendered for a capability whether or not it is on, with its
  // controls inert until it is - so this runs after the switch above, not
  // before.
  const approval = settings.getByLabel("Human approval");
  if (await approval.isVisible()) {
    await approval.click();
    await page.getByRole("option", { name: "Never ask" }).click();
  }
  await settings.getByRole("button", { name: "Close", exact: true }).click();
  await expect(settings).toBeHidden();

  // 5. publishing
  const publish = page.getByRole("button", { name: "Publish" });
  await expect(publish, "the owner must be able to publish agents").toBeVisible();
  await publish.click();

  // The first publish creates the production environment, and the dialog says
  // so before it happens (#519) - confirming is what actually publishes.
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();

  // Publishing validates the draft first, so this is also the assertion that the
  // spec the Builder wrote is one the API accepts. The status badge lives in the
  // page title, and it is the only thing that unlocks the chat action below.
  await expect(pageStatus(page)).toContainText("published", { timeout: 30_000 });
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
  await expect(composer).toHaveText("");
  await expect(page.getByRole("main").getByText(answerToken)).toBeVisible({ timeout: 120_000 });

  // 7. the same agent, reached by a link and nothing else
  //
  // #517's own bar: publishing produces a URL, and opening it signed into
  // nothing answers a question. Reusing this journey's agent is the point rather
  // than a shortcut - the token can only have come from the instructions
  // published in step 5, so seeing it again here proves the hosted page reached
  // the *same frozen version* through the same runner, which is the claim the
  // whole surface rests on.
  // The origin Playwright is actually on, read off the page rather than rebuilt
  // from the config: it has to be the origin the backend admits a hosted page
  // from, and a second copy of the port is a second thing to disagree.
  const origin = new URL(page.url()).origin;

  await page.goto(`/agents/${agentId}`);
  await page.getByRole("tab", { name: "Availability" }).click();
  const availability = page.getByRole("tabpanel");
  const publishPage = availability.getByRole("button", { name: /^Hosted page/ });
  await expect(publishPage, "the owner must be able to publish a hosted page").toBeVisible();
  await publishPage.click();

  // The form is open once its own field is on screen. Waited for rather than
  // assumed: `getByLabel("Allowed sites")` is absent from the picker too, so it
  // asserts nothing about the click having landed, and the submit below would
  // then find the picker's Public API card - whose name ends "Nothing to publish
  // here", which a substring match on `Publish` counts (#634).
  await expect(
    availability.getByLabel("Name"),
    "the hosted-page form never opened, so the Publish below would find the picker's card",
  ).toBeVisible();

  // No allowed site, and that is the assertion rather than an omission: an
  // allow-list is a rule about other people's sites, and this page is ours. The
  // form used to demand one before it would publish anything, which made the
  // shortest integration this product has - send somebody a link - impossible to
  // create without inventing a site.
  await expect(availability.getByLabel("Allowed sites")).toHaveCount(0);

  // **Armed before the click, awaited after it.** `click()` returns when the
  // click is dispatched, not when the request it starts is answered - and the
  // `reload()` below navigates, which aborts whatever is still in flight. So the
  // publish that this whole section is about was sometimes cancelled before the
  // server saw it, and the 30-second wait for a link then expired on an embed
  // that had never been created. That is #1474, four failures in nine runs on
  // branches that touch none of this.
  const published = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/agents/embeds" &&
      response.request().method() === "POST" &&
      // A 401 on this path is not the answer, for the reason `submitDialog` gives
      // at length: `apiClient.send` recovers from an expired access token by
      // refreshing and re-issuing the same write, so stopping at the first
      // response would fail a publish that succeeded on the retry - a new flake
      // in place of the one being removed.
      response.status() !== 401,
  );
  await availability.getByRole("button", { name: "Publish", exact: true }).click();
  expect((await published).ok(), "publishing the hosted page was refused").toBe(true);

  // And the row is readable before the DOM is asked about it, by polling the API
  // rather than by reloading and hoping - the shape every fixture step takes
  // after #335. The refetch after a write is sometimes answered with the
  // pre-write list (#230), which a reload narrows rather than closes.
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/agents/${agentId}/embeds`);
        if (!response.ok()) return [];
        const body = (await response.json()) as { items?: { public_key?: string }[] };
        // `public_key` is what the hosted link is built from, so this polls for
        // exactly the thing the assertion below reads off the page.
        return (body.items ?? []).map((embed) => embed.public_key).filter(Boolean);
      },
      { message: "the publish was accepted, but the agent lists no embed" },
    )
    .not.toHaveLength(0);

  await page.reload();
  await page.getByRole("tab", { name: "Availability" }).click();
  const link = page.getByText(new RegExp(`^${origin}/e/`)).first();
  await expect(link).toBeVisible({ timeout: 30_000 });
  const hostedUrl = (await link.textContent())?.trim() ?? "";
  expect(hostedUrl).toMatch(new RegExp(`^${origin}/e/[A-Za-z0-9_-]+$`));

  // A context of its own, with no storage state: nobody is signed in, no
  // organization header, none of the console. That is the whole claim, and
  // reusing `page` would have proved nothing about it.
  const stranger = await browser.newContext();
  const hosted = await stranger.newPage();
  try {
    await hosted.goto(hostedUrl);
    const ask = hosted.getByRole("textbox", { name: "Ask a question…" });
    await expect(ask).toBeEnabled({ timeout: 30_000 });
    await ask.fill("Say the word.");
    await expectComposerAlignment(hosted);
    await hosted.getByRole("button", { name: "Send" }).click();
    await expect(hosted.getByText(answerToken)).toBeVisible({ timeout: 120_000 });
    const phone = await browser.newContext({
      viewport: { width: 390, height: 844 },
      hasTouch: true,
      isMobile: true,
    });
    try {
      const phonePage = await phone.newPage();
      await phonePage.goto(hostedUrl);
      await phonePage.getByRole("textbox", { name: "Ask a question…" }).fill("A phone draft");
      await expectComposerAlignment(phonePage);
    } finally {
      await phone.close();
    }
  } finally {
    await stranger.close();
  }

  // 8. the run in Activity
  await page.goto("/runs");
  await expect(
    pageHeading(page, "Activity"),
    "the Activity page never drew its heading",
  ).toBeVisible();
  await page.getByRole("tab", { name: "Runs", exact: true }).click();

  // A run records the named model it billed against, which is how the row is
  // found — and a cost, which is the proof that usage was metered rather than
  // merely executed.
  //
  // **The API says the run is priced before the page is asked to draw it, and
  // #162 is why.** This step asserted straight on the row, and failed on `main`
  // with `element(s) not found` — on a commit whose own pull request had passed
  // and whose re-run passed again. It is the last step of the longest journey
  // here and it crosses the most: the model provider answered, the run row was
  // written, the usage was metered into a spend record, and the list refetched.
  // A bare `toBeVisible()` on that says "one of those five did not happen" and
  // nothing else. Polling the collection first splits it in two: a failure here
  // is a run that was never priced, a failure below is a page that did not draw
  // a row the API was serving.
  const priced = await nowMatching(
    page.request,
    // Scoped to this journey's own agent rather than read off the first page of
    // everything: CI's organization is shared with every other spec, and a run
    // pushed past `limit` by a busy list would read as a run that never happened.
    `/api/runs?agent_id=${agentId}`,
    (run) => run["model_label"] === modelLabel && Number(run["cost_usd"] ?? 0) > 0,
    `a run billed against ${modelLabel} carrying a cost`,
  );

  const row = page.getByRole("row").filter({ hasText: modelLabel }).first();
  await expect(
    row,
    `run ${String(priced["id"])} is priced at ${String(priced["cost_usd"])}, but Activity draws no row for ${modelLabel}`,
  ).toBeVisible();
  await expect(row, "the run row is on screen without the cost the API reports").toContainText(
    /\$\d+\.\d{4}/,
  );

  // Curate the chat response through Activity, then read the actual saved case.
  // The hosted run can be newest, so select the web-chat run explicitly.
  const chatRun = await nowMatching(
    page.request,
    `/api/runs?agent_id=${agentId}`,
    (run) => run["surface"] === "web" && run["status"] === "completed",
    "the completed chat run",
  );
  const datasetName = `Activity answers ${stamp}`;
  await page.goto("/datasets");
  await page.getByRole("button", { name: "New dataset", exact: true }).first().click();
  const datasetDialog = page.getByRole("dialog");
  await datasetDialog.getByRole("textbox", { name: /^Name/ }).fill(datasetName);
  await submitDialog(page, {
    dialog: datasetDialog,
    submit: datasetDialog.getByRole("button", { name: "Create", exact: true }),
    path: "/api/datasets",
  });
  await page.waitForURL(/\/datasets\/[^/?]+$/);
  const datasetId = new URL(page.url()).pathname.split("/").pop();
  if (!datasetId) throw new Error("Created dataset has no identity");
  await page.goto(`/runs?run=${String(chatRun["id"])}&dataset=${datasetId}`);
  await page.getByRole("button", { name: "Add to dataset", exact: true }).click();
  const addDialog = page.getByRole("dialog");
  await expect(addDialog.getByRole("combobox", { name: "Dataset", exact: true })).toHaveText(
    datasetName,
  );
  await expect(addDialog.getByRole("radio", { name: /Reference answer/ })).toBeChecked();
  await addDialog.getByText("View source messages", { exact: true }).click();
  await expect(addDialog.getByText("Say the word.", { exact: true })).toBeVisible();
  await expect(addDialog.getByText(answerToken, { exact: true })).toBeVisible();
  await submitDialog(page, {
    dialog: addDialog,
    submit: addDialog.getByRole("button", { name: "Add", exact: true }),
    path: `/api/datasets/${datasetId}/cases/from-message`,
  });
  const savedCase = await nowMatching(
    page.request,
    `/api/datasets/${datasetId}/cases`,
    (item) => item["input"] === "Say the word.",
    "the case curated from Activity",
  );
  expect(savedCase["reference_answer"]).toBe(answerToken);
  expect(savedCase["counter_example"]).toBeNull();
  expect(savedCase["history"]).toEqual([]);

  // 9. cleaning up
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
  // key - because the API refuses to orphan either. The embed published in step
  // 7 needs no line of its own: `agent_embeds.agent_id` is `ON DELETE CASCADE`,
  // and the visitor row cascades from the embed.
  for (const path of [
    `/api/datasets/${datasetId}`,
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

/** Geometry assertions catch misplaced padding as well as stretched icon buttons. */
async function expectComposerAlignment(page: import("@playwright/test").Page): Promise<void> {
  const form = await page.locator("form").boundingBox();
  const input = await page.getByRole("textbox", { name: "Ask a question…" }).boundingBox();
  const button = await page.getByRole("button", { name: "Send", exact: true }).boundingBox();
  const icon = await page
    .getByRole("button", { name: "Send", exact: true })
    .locator("svg")
    .boundingBox();
  if (!form || !input || !button || !icon)
    throw new Error("Hosted composer controls must have visible bounds");
  expect(Math.abs(button.width - button.height)).toBeLessThanOrEqual(0.5);
  const center = form.y + form.height / 2;
  expect(Math.abs(input.y + input.height / 2 - center)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(button.y + button.height / 2 - center)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(icon.y + icon.height / 2 - center)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(icon.x + icon.width / 2 - button.x - button.width / 2)).toBeLessThanOrEqual(0.5);
}
