import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import {
  AUTH_STATE,
  CAPABILITY_TOOL,
  CAPABILITY_WITH_TOOLS,
  DRAFT_AGENT_NAME,
  RENAMED_TOOL,
  SEEDED_AGENT_HANDLE,
  SEEDED_AGENT_NAME,
  SEEDED_MODEL_LABEL,
  SEEDED_ORG_MCP_NAME,
  SEEDED_SECRET_HINT,
  SEEDED_SECRET_NAME,
  agentCard,
  expectNoRenderedSecret,
  openAgent,
  openBuilderTab,
  pageHeading,
  saveDraft,
  selectSavedModel,
  unsaved,
} from "./helpers";

/**
 * The entry for one capability in the Builder's list, which is what opens its
 * panel.
 *
 * Anchored to the start of the accessible name because the entry prints its
 * tool count after the name ("Knowledge search 1 tool"). It is the only *button*
 * bearing the capability's name - the two controls that grant it are switches,
 * named "Give this agent Knowledge search" and "Knowledge search enabled".
 */
function capabilityEntry(page: Page, name: string): Locator {
  return page.getByRole("button", { name: new RegExp(`^${name}\\b`) });
}

/**
 * The panel the Builder shows for one capability, opened first.
 *
 * The Builder is master–detail now: one panel at a time, for whichever
 * capability is focused, and switching a capability on deliberately does not
 * focus it — reading what a capability offers and granting it are different
 * gestures. Nothing is focused after a reload either, so the click is what
 * makes the panel below the one a spec means rather than whichever one the
 * component's fallback happened to pick.
 */
async function capabilityPanel(page: Page, name: string): Promise<Locator> {
  await capabilityEntry(page, name).click();
  const panel = page.getByRole("group", { name, exact: true });
  await expect(panel).toBeVisible();
  return panel;
}

/**
 * The row for `CAPABILITY_TOOL`, read off whatever is currently on screen.
 *
 * Found by the tool's stable id, which is what the row is labelled with — the
 * name printed in it is editable, and one of the specs below edits it.
 */
async function toolRow(page: Page): Promise<Locator> {
  // The tab, every time: these specs reload to prove what came back from the
  // API, and a reload puts the Builder back on Build - where no capability is
  // mounted at all.
  await openBuilderTab(page, "Toolbox");
  const panel = await capabilityPanel(page, CAPABILITY_WITH_TOOLS);
  // Settings and Tools are two tabs inside the panel: a capability's own form
  // and approval on one, the prompt text of each tool on the other, because a
  // rich capability made one scroll of two unrelated jobs.
  await panel.getByRole("tab", { name: "Tools", exact: true }).click();
  const row = panel.getByRole("listitem", { name: CAPABILITY_TOOL });
  await expect(row).toBeVisible();
  return row;
}

/**
 * What the generated config form labels a schema field.
 *
 * The form titles a property the way a JSON Schema does - `max_results` becomes
 * "Max Results" - so a spec that knows the field name still has to know that
 * rule to find the control.
 */
function fieldLabel(field: string): string {
  return field
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * The checkbox that binds one MCP server, found through the picker's search.
 *
 * The picker is a catalog now rather than a list of what is connected - every
 * server this deployment knows, connected or not - so the organization's own is
 * one row among thirty and off screen until it is searched for.
 */
async function findServer(page: Page, name: string): Promise<Locator> {
  await page.getByPlaceholder("Search servers…").fill(name);
  const server = page.getByRole("checkbox", { name, exact: true });
  await expect(server).toBeVisible();
  return server;
}

/**
 * The switch that grants one capability, in the list it is picked from.
 *
 * A switch rather than a checkbox: this is one capability being on or off, not
 * one of a set. The panel on the right carries a second switch for the same
 * capability, labelled `<name> enabled` - two controls doing the same thing is
 * fine, two answering to the same accessible name is not, which is why this one
 * keeps the "Give this agent" wording.
 */
function capabilitySwitch(page: Page, name: string): Locator {
  return page.getByRole("switch", { name: `Give this agent ${name}`, exact: true });
}

/** The Builder, open on the draft agent with the tool-bearing capability on. */
async function openToolRow(page: Page): Promise<Locator> {
  await openAgent(page, DRAFT_AGENT_NAME);
  await openBuilderTab(page, "Toolbox");

  const capability = capabilitySwitch(page, CAPABILITY_WITH_TOOLS);
  await expect(capability).toBeVisible();
  // These specs save the draft, so a second run opens an agent that already has
  // the capability on — clicking then would switch it off.
  if ((await capability.getAttribute("aria-checked")) !== "true") {
    await capability.click();
    await expect(capability).toHaveAttribute("aria-checked", "true");
  }

  return await toolRow(page);
}

/**
 * As much of a catalog entry as the secret spec below reads.
 *
 * Deliberately not the app's `CapabilityCatalogEntry`: this suite talks to the
 * API over HTTP and asserts on what came back, so a type imported from the code
 * under test would make a field the API stopped sending a compile-time fact
 * rather than a failing test.
 */
interface CatalogEntry {
  id: string;
  name: string;
  requires_secret: {
    kind: string;
    description: string;
    /** Null when the key is always needed; otherwise the config that needs it. */
    required_when: { field: string; equals: string[] } | null;
  } | null;
}

type NeedsSecret = CatalogEntry & { requires_secret: { kind: string; description: string } };

test.use({ storageState: AUTH_STATE });

/**
 * The Builder, on its own.
 *
 * The end-to-end path an agent takes — key, model, capability, publish, run —
 * lives in `journey.spec.ts`. What is checked here is the smaller promise the
 * Builder makes on every visit: it lists the agents that exist, it will not let
 * you create a nameless one, and it will not offer to chat with something
 * nobody published.
 */

test.describe("Agents", () => {
  test("lists the agent the seed published, by name and by handle", async ({ page }) => {
    await page.goto("/agents");
    await expect(pageHeading(page, "Agents")).toBeVisible();

    // The handle, not just the name: it is what the agent is addressed by from
    // Slack and the API, it is derived from the name once and then frozen, and
    // it is the one string on this card nobody could have typed by accident.
    const card = agentCard(page, SEEDED_AGENT_HANDLE);
    await expect(card).toBeVisible();
    await expect(card).toContainText(SEEDED_AGENT_NAME);
    await expect(card).toContainText("published");

    // Offered only to a role the permission catalog says may create agents, so
    // its presence also says /me/permissions answered.
    await expect(page.getByRole("button", { name: "New agent" })).toBeVisible();
  });

  test("creating an agent requires a name", async ({ page }) => {
    await page.goto("/agents");
    await expect(pageHeading(page, "Agents")).toBeVisible();

    await page.getByRole("button", { name: "New agent" }).click();

    const dialog = page.getByRole("dialog");
    const create = dialog.getByRole("button", { name: "Create", exact: true });

    // The name becomes the handle the agent is mentioned by and cannot be
    // changed afterwards, so an empty one has to be refused up front rather
    // than corrected later.
    await expect(create).toBeDisabled();

    await dialog.getByLabel("Name").fill("   ");
    await expect(create).toBeDisabled();

    await dialog.getByLabel("Name").fill("E2E Support");
    await expect(create).toBeEnabled();
  });

  test("a name whose handle is taken is refused on the field, not in a toast", async ({ page }) => {
    // The whole journey, end to end: the browser derives a handle, the server
    // refuses it, the proxy carries the refusal back with its status and body
    // intact, and the dialog puts it under the input that produced it. Every
    // link is somewhere else — a unit test can prove the dialog renders what it
    // is handed and nothing more.
    await page.goto("/agents");
    await expect(pageHeading(page, "Agents")).toBeVisible();
    // Asserted against the seed rather than against whatever is in the
    // database: the name typed below has to be one that provably exists.
    await expect(agentCard(page, SEEDED_AGENT_HANDLE)).toBeVisible();

    await page.getByRole("button", { name: "New agent" }).click();
    const dialog = page.getByRole("dialog");
    const name = dialog.getByLabel("Name");

    await name.fill(SEEDED_AGENT_NAME);
    // Before anything is sent: the handle the name will produce is on screen,
    // which is what makes the refusal below legible rather than a message about
    // a value nobody entered.
    await expect(dialog.getByText(SEEDED_AGENT_HANDLE, { exact: true })).toBeVisible();

    await dialog.getByLabel("Description").fill("A second one, which should not be created.");
    await dialog.getByRole("button", { name: "Create", exact: true }).click();

    // Beside the field and marked on the control, not a red toast that leaves
    // nothing behind — and naming the handle rather than the name, because the
    // handle is what was refused and what has to change.
    await expect(
      dialog.getByText(new RegExp(`${SEEDED_AGENT_HANDLE} is already taken`)),
    ).toBeVisible();
    await expect(name).toHaveAttribute("aria-invalid", "true");

    // Still on the form, still filled in, and nothing was created — a refusal
    // that cost a keystroke rather than the whole dialog.
    await expect(name).toHaveValue(SEEDED_AGENT_NAME);
    await expect(dialog.getByLabel("Description")).toHaveValue(
      "A second one, which should not be created.",
    );
    await expect(page).toHaveURL(/\/agents$/);

    // And it stops being wrong the moment the name does.
    await name.fill(`${SEEDED_AGENT_NAME} 2`);
    await expect(name).not.toHaveAttribute("aria-invalid", "true");
  });

  test("the builder opens on the agent's stored configuration", async ({ page }) => {
    await openAgent(page, SEEDED_AGENT_NAME);

    // Every one of these came back from the API rather than from a default: the
    // published state, the description bootstrap wrote, the instructions the
    // model will actually be given, and the named model a run bills against. A
    // Builder that renders its shell while the agent fails to load shows the
    // same headings and none of this.
    await expect(pageHeading(page)).toContainText("published");
    await expect(page.getByText("Explains what this platform does")).toBeVisible();

    await expect(page.getByRole("textbox", { name: "Instructions" })).toHaveValue(
      /You are a helpful assistant running on AgenticOS/,
    );

    // The model section leads with the profile this agent actually runs on, and
    // that summary is what proves `model_profile_id` came back: it renders only
    // for an id that resolves to one of the organization's profiles. A Builder
    // that dropped the field and fell back to "Organization default" would draw
    // no such row at all. The saved-profile list is one disclosure below and is
    // a way to change the answer, not a statement of it.
    await expect(
      page.getByRole("group", { name: "Current model" }).getByText(SEEDED_MODEL_LABEL),
    ).toBeVisible();
    // One tab over, because the capability list is not on Build - and what is
    // being proved is the same thing: the binding came back from the API.
    await openBuilderTab(page, "Toolbox");
    await expect(capabilitySwitch(page, "Date and time")).toHaveAttribute("aria-checked", "true");
  });

  test("an unpublished agent cannot be opened in chat", async ({ page }) => {
    // A draft is the only thing that proves anything here; opening whichever
    // agent happens to be first would pass or fail on the seed rather than on
    // the behaviour. `seed.setup.ts` creates one, so this never has to skip.
    await openAgent(page, DRAFT_AGENT_NAME);
    await expect(pageHeading(page)).toContainText("draft");

    // The chat runs the published version and its picker offers nothing else, so
    // a draft has nothing to open — and the control says what unlocks it rather
    // than dropping the reader into a chat that would answer as somebody else.
    const openInChat = page.getByRole("button", { name: "Open in chat" });
    await expect(openInChat).toBeDisabled();
    await expect(openInChat).toHaveAttribute("title", /Publish this agent/);
  });

  test("a published agent opens in a chat addressed to it", async ({ page }) => {
    await openAgent(page, SEEDED_AGENT_NAME);
    await expect(pageHeading(page)).toContainText("published");

    await page.getByRole("button", { name: "Open in chat" }).click();
    // Generous, because the client router commits the URL only once /chat has
    // been fetched — against a dev server that is a first compile, not a hang.
    await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });

    // The URL is not the assertion — landing on /chat with the general
    // assistant selected would be the failure this replaced the Test tab to
    // avoid. Who answers is its own control beside the composer now, and it is
    // labelled with whoever that is, so this is the proof that the agent came
    // along rather than only the navigation.
    await expect(
      page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
    ).toBeVisible();
  });

  test("one tool can be held for approval while the rest of its capability is not", async ({
    page,
  }) => {
    // The only spec that can prove this: jsdom cannot open a Radix select, so
    // the unit tests assert that a stored mode reaches the control and stop
    // there. Everything below the click — the spec the Builder assembles, the
    // draft the API stores, the spec it hands back — is only exercised here.
    const tool = await openToolRow(page);

    // Establish the starting state rather than assume it. This test asserts on
    // a *transition* — an unsaved change appearing — so it needs the override
    // absent to begin with. Cleaning up at the end is not enough: a run that
    // fails before its teardown leaves the next one with nothing to change,
    // and then the suite fails for a reason that has nothing to do with the
    // behaviour under test.
    if (!(await tool.getByRole("combobox").textContent())?.includes("Follow the capability")) {
      await tool.getByRole("combobox").click();
      await page.getByRole("option", { name: "Follow the capability" }).click();
      await saveDraft(page);
    }

    await tool.getByRole("combobox").click();
    await page.getByRole("option", { name: "Always ask" }).click();
    await expect(tool.getByText("overridden")).toBeVisible();

    // Only then is there anything to save: the badge in the title is the
    // Builder saying the draft on screen differs from the one on the server.
    await expect(unsaved(page)).toBeVisible();
    await saveDraft(page);

    await page.reload();

    // Re-read from scratch, because the point is what came back from the API
    // rather than what React still had in memory.
    const saved = await toolRow(page);
    await expect(saved.getByRole("combobox")).toContainText("Always ask");
    await expect(saved.getByText("overridden")).toBeVisible();

    // And the capability it belongs to was left alone — an override that quietly
    // gated everything would look identical on the row that was clicked.
    //
    // Read off the Settings tab, by the label of the capability's own control.
    // It used to be `.first()` combobox in the panel, which was true when the
    // panel was one flat body and stopped being true when #914 gave it tabs:
    // Radix unmounts the inactive tab, so on Tools the only comboboxes in the
    // group are the tool rows' — and `.first()` was `search_documents`, the very
    // row this test had just set to "Always ask". The assertion passed for a
    // year and then failed for being right about the wrong element.
    const panel = page.getByRole("group", { name: CAPABILITY_WITH_TOOLS, exact: true });
    await panel.getByRole("tab", { name: "Settings", exact: true }).click();

    await expect(panel.getByLabel("Human approval")).toContainText("Follow the capability");
  });

  test("a tool renamed for one agent sticks, and the code default can be had back", async ({
    page,
  }) => {
    // A tool's name is prompt, not labelling: the model emits it verbatim and
    // picks differently because of it. Everything between the keystroke and the
    // name a run would really offer — the override the Builder assembles, the
    // draft the API stores, the effective name it resolves and hands back —
    // exists only here; a unit test can prove the field renders and no more.
    let tool = await openToolRow(page);
    const name = tool.getByLabel("Name", { exact: true });

    // Establish the starting state rather than assume it, for the same reason
    // the spec above does: this asserts on a change away from the code default,
    // so a run that failed before undoing its rename must not leave the next
    // one with nothing to change. Keyed on the reset button rather than the
    // row's badge, which a leftover approval override also lights up.
    // Both fields, not just the name. This cleared the name and then asserted
    // further down that the *description* was untouched — so a leftover
    // description override from any earlier run failed the spec on a field it
    // had just refused to clean. Half a reset is the same bug as no reset.
    let cleaned = false;
    for (const field of ["name", "description"] as const) {
      const reset = tool.getByRole("button", { name: `Reset ${field}` });
      if (await reset.isVisible()) {
        await reset.click();
        cleaned = true;
      }
    }
    if (cleaned) await saveDraft(page);
    await expect(name).toHaveValue(CAPABILITY_TOOL);

    await name.fill(RENAMED_TOOL);
    await expect(tool.getByText("overridden")).toBeVisible();
    await expect(unsaved(page)).toBeVisible();
    await saveDraft(page);

    await page.reload();

    tool = await toolRow(page);
    await expect(tool.getByLabel("Name", { exact: true })).toHaveValue(RENAMED_TOOL);

    // The description was never touched, so it is still the one the capability
    // declares — an override that wrote both would be indistinguishable on the
    // field that was typed into.
    await expect(tool.getByRole("button", { name: "Reset description" })).toBeHidden();

    // The way back, without anyone having to remember what the tool was called
    // an hour ago. Saved and re-read, because a field that only looks reverted
    // is the failure this is here to catch.
    await tool.getByRole("button", { name: "Reset name" }).click();
    await saveDraft(page);

    await page.reload();

    tool = await toolRow(page);
    await expect(tool.getByLabel("Name", { exact: true })).toHaveValue(CAPABILITY_TOOL);
    await expect(tool.getByRole("button", { name: "Reset name" })).toBeHidden();
  });

  // Capabilities the Builder gives a section of their own, so they are not rows in
  // the picker and cannot be driven through it. `sandbox` is here because its
  // configuration is a choice between four backends with different infrastructure
  // behind them, one of which shares files between people - and because it
  // registers before `web_research`, so a search for "something that needs a
  // secret" finds it first and then cannot find its switch.
  const OWN_SECTION = new Set(["sandbox", "skills", "thinking"]);

  test("a capability that needs a secret says so until it has one, and keeps the one it is given", async ({
    page,
  }) => {
    // The only place this can be proved. jsdom cannot open a Radix select, so the
    // unit tests assert that a stored reference reaches the control and stop
    // there; everything below the click — the spec the Builder assembles, the
    // draft the API stores, the reference it hands back — is only exercised here.
    //
    // It skips itself while no capability in the deployment declares a secret,
    // which is every deployment today: no builtin needs one, and the picker
    // renders only for one that does. A skip with a reason is the honest report —
    // the alternative is a spec that passes by asserting nothing. The day a
    // capability declares an API-key secret, this starts exercising it without
    // anyone remembering to come back for it.
    const catalog = await page.request.get("/api/agents/capabilities");
    expect(catalog.ok(), "the capability catalog did not answer").toBeTruthy();
    const { items } = (await catalog.json()) as { items: CatalogEntry[] };
    // An api_key one specifically: the seed stores exactly one secret and it is
    // an API key, and a picker filtered by kind would offer nothing for any other
    // requirement — correctly, which is a different spec than this one.
    const needy = items.find(
      (entry): entry is NeedsSecret =>
        entry.requires_secret?.kind === "api_key" && !OWN_SECTION.has(entry.id),
    );
    if (needy === undefined) {
      test.skip(
        true,
        "no capability in this deployment declares an api_key secret, so the Builder renders no picker to drive",
      );
      return;
    }

    await openAgent(page, DRAFT_AGENT_NAME);
    await openBuilderTab(page, "Toolbox");
    const capability = capabilitySwitch(page, needy.name);
    await expect(capability).toBeVisible();

    // Establish the starting state rather than assume it, as the specs above do —
    // and off-then-on rather than clearing the choice, because the picker
    // deliberately offers no way to unselect: unset is the state that blocks
    // publishing, so it is reached by not having chosen, never by choosing.
    if ((await capability.getAttribute("aria-checked")) === "true") await capability.click();
    await capability.click();
    await expect(capability).toHaveAttribute("aria-checked", "true");

    const group = await capabilityPanel(page, needy.name);

    // The picker's behaviour depends on which shape of requirement this is. A
    // *conditional* one (Web search takes a key for Tavily and none for
    // DuckDuckGo) asks for nothing until the configuration that needs it is
    // chosen, so a flat requirement would lock the free default behind an
    // account - the picker is absent until the condition is met. An
    // *unconditional* one (image generation always needs a provider key) asks
    // from the moment the capability is on.
    const condition = needy.requires_secret.required_when;
    if (condition !== null) {
      await expect(group.getByLabel("Secret")).toHaveCount(0);
      await group.getByLabel(fieldLabel(condition.field)).click();
      await page.getByRole("option", { name: condition.equals[0]!, exact: true }).click();
    }

    const picker = group.getByLabel("Secret");

    // What the capability's author wrote about why it needs a credential, which
    // is the only explanation whoever picks one will get.
    await expect(group.getByText(needy.requires_secret.description)).toBeVisible();
    // And the refusal that would otherwise arrive from a publish attempt, in a
    // list beside everything else wrong with the agent.
    await expect(group.getByText(/cannot be published until it has one/)).toBeVisible();

    await picker.click();
    await page.getByRole("option", { name: new RegExp(SEEDED_SECRET_NAME) }).click();

    // The name and the hint: two keys for the same service are told apart by
    // nothing else, and neither the API nor this page can show the value.
    await expect(picker).toContainText(SEEDED_SECRET_NAME);
    await expect(picker).toContainText(SEEDED_SECRET_HINT);
    await expect(group.getByText(/cannot be published until it has one/)).toBeHidden();

    // Stored, without asserting the badge on the way: this spec walks through
    // two selects and a catalog read, which is long enough for the Builder's own
    // 1.2s autosave to have already saved it. That the badge appears at all is
    // the approval spec's assertion, where the edit is one click.
    await saveDraft(page);
    await page.reload();

    // Re-read from scratch, because the point is the reference that came back
    // from the API rather than what React still had in memory.
    await openBuilderTab(page, "Toolbox");
    const saved = await capabilityPanel(page, needy.name);
    await expect(saved.getByLabel("Secret")).toContainText(SEEDED_SECRET_NAME);
    await expect(saved.getByText(/cannot be published until it has one/)).toBeHidden();

    // Nowhere on this page, at any point, is the value itself.
    await expectNoRenderedSecret(page);
  });

  test("a temperature set in the Builder sticks, and can be given back to the provider", async ({
    page,
  }) => {
    // The one path a unit test cannot cover: the number the slider produces,
    // the spec the Builder assembles, the draft the API stores, and what comes
    // back on a fresh load. The state that matters most is the one on the far
    // side of the reset — a setting given back has to arrive as an *absent*
    // key, and a `null` that survived the round trip would look identical here
    // until a reasoning model refused the run.
    await openAgent(page, DRAFT_AGENT_NAME);

    const temperature = page.getByLabel("Temperature");
    const reset = page.getByRole("button", { name: "Use provider default" });

    // Establish the starting state rather than assume it: this asserts on a
    // transition away from unset, and a run that failed before its own cleanup
    // would otherwise leave the next one with nothing to change.
    if (await reset.isVisible()) {
      await reset.click();
      await saveDraft(page);
    }
    await expect(page.getByText("Provider default").first()).toBeVisible();

    // Keyboard, not a drag: jsdom aside, a real slider has a track and this one
    // moves by its step, so the value is predictable rather than wherever the
    // pointer landed.
    await temperature.focus();
    await temperature.press("ArrowLeft");
    await expect(temperature).toHaveValue("0.95");
    await expect(unsaved(page)).toBeVisible();
    await saveDraft(page);

    await page.reload();

    await expect(page.getByLabel("Temperature")).toHaveValue("0.95");
    await expect(page.getByText("0.95")).toBeVisible();

    // And the way back, which has to remove the key rather than write a zero:
    // "no temperature" is the only thing a reasoning model accepts.
    await page.getByRole("button", { name: "Use provider default" }).click();
    await saveDraft(page);

    await page.reload();

    await expect(page.getByRole("button", { name: "Use provider default" })).toBeHidden();
    await expect(page.getByText("Provider default").first()).toBeVisible();
  });

  test("an MCP server can be bound to an agent, and it survives publishing", async ({ page }) => {
    // The picker existed and was mounted nowhere, because `mcp_server_ids`
    // could only be filled with something publish refuses. This asserts the
    // whole of what changed: the Builder offers the organization's servers, the
    // choice reaches the stored draft, and the spec publishes with it — which
    // it could not do while the only connectable servers were personal.
    await openAgent(page, DRAFT_AGENT_NAME);
    // Its own tab since the servers left the Toolbox: the picker embeds the
    // whole catalog, and it was pushing the capability workbench off screen.
    await openBuilderTab(page, "MCP servers");

    const server = await findServer(page, SEEDED_ORG_MCP_NAME);

    if ((await server.getAttribute("aria-checked")) !== "true") {
      await server.click();
      await expect(unsaved(page)).toBeVisible();
      await saveDraft(page);
    }

    await page.reload();
    await openBuilderTab(page, "MCP servers");
    await expect(await findServer(page, SEEDED_ORG_MCP_NAME)).toHaveAttribute(
      "aria-checked",
      "true",
    );

    // The seeded draft is created with a name and nothing else, so the first
    // thing publish refuses it for is having no model - which says nothing about
    // the MCP binding this test is about. Naming one is what makes the assertion
    // below a statement about the server rather than about the fixture.
    await openBuilderTab(page, "Build");
    await selectSavedModel(page, SEEDED_MODEL_LABEL);
    await saveDraft(page);

    // The refusal this whole change was blocked on. Publishing a spec that
    // named an org server used to be impossible because no org server could
    // exist; if it is still impossible, `/validate` refuses and its body names
    // which problem. Asserted on the answer rather than on the problems panel
    // being absent: `toBeHidden()` passes on an element that has not rendered
    // yet, so the version of this check that ran at click time asserted nothing
    // at all and hid exactly this failure (#519).
    const validated = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/validate") &&
        response.request().method() === "POST",
      { timeout: 15_000 },
    );
    await page.getByRole("button", { name: "Publish" }).click();

    const verdict = await validated;
    const refusal = verdict.ok() ? "" : await verdict.text();
    expect(verdict.ok(), `POST /validate answered ${verdict.status()}: ${refusal}`).toBe(true);

    // Only a draft the API accepted is offered the dialog, so its opening is the
    // validation passing (#519).
    await expect(page.getByRole("dialog").getByRole("button", { name: "Publish" })).toBeVisible();
  });
});
