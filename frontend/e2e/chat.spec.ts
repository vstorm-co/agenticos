import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, SEEDED_AGENT_HANDLE, SEEDED_AGENT_NAME, agentCard } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Chat.
 *
 * The composer is disabled until the websocket to the backend is up, which
 * makes it the one control in the product that states its own connectivity:
 * "Live" next to an enabled box is proof the browser reached the backend
 * directly, not merely that Next rendered a page. Every test here waits for
 * that rather than for a spinner to go away.
 *
 * What can be proven without a provider key is everything up to the model:
 * the message is accepted, a conversation is created for it, and both survive a
 * reload. The answer itself needs a key and real money, so it lives in
 * `journey.spec.ts`.
 */

/** The composer, once the socket is up. Disabled means "not connected". */
async function readyComposer(page: Page) {
  await page.goto("/chat");
  await expect(page.getByText("Live")).toBeVisible();

  const input = page.getByRole("textbox", { name: "Type a message..." });
  await expect(input).toBeEnabled();
  return input;
}

test.describe("Chat", () => {
  test("the composer is live, not merely rendered", async ({ page }) => {
    const input = await readyComposer(page);

    // Disabled until there is something to send: an empty message would open a
    // conversation with nothing in it.
    await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();

    await input.fill("Hello, AI assistant!");
    await expect(input).toHaveValue("Hello, AI assistant!");
    await expect(page.getByRole("button", { name: "Send message" })).toBeEnabled();
  });

  test("a sent message becomes a conversation that outlives the page", async ({ page }) => {
    // Unique, so this asserts on the message this test sent rather than on one
    // left behind by a previous run.
    const message = `E2E hello ${Date.now().toString(36)}`;

    const input = await readyComposer(page);
    await input.fill(message);
    await page.getByRole("button", { name: "Send message" }).click();

    // Cleared, so the transcript assertion below cannot be satisfied by the box
    // the text was typed into.
    await expect(input).toHaveValue("");
    await expect(page.getByText(message)).toBeVisible();

    // The sidebar is fed by the conversations API, and the title is derived
    // server-side from the first message. Its appearance is the proof that the
    // message reached the backend rather than only the DOM.
    // Inside `main`: the layout's navigation is a `complementary` landmark too,
    // and it is the one that comes first in the DOM.
    const conversations = page.getByRole("main").getByRole("complementary");
    await expect(conversations.getByText(message)).toBeVisible();

    // And it is still there on a fresh page load, which no client-side state
    // could fake.
    await page.reload();
    await expect(conversations.getByText(message)).toBeVisible();
    await conversations.getByText(message).click();
    await expect(page.getByRole("main").getByText(message).first()).toBeVisible();
  });

  test("Enter sends, Shift+Enter does not", async ({ page }) => {
    const message = `E2E keyboard ${Date.now().toString(36)}`;

    const input = await readyComposer(page);
    await input.fill("Line 1");
    await input.press("Shift+Enter");
    await input.pressSequentially("Line 2");
    // Still in the box: Shift+Enter is a newline, not a send.
    await expect(input).toHaveValue(/Line 1[\s\S]*Line 2/);

    await input.fill(message);
    await input.press("Enter");
    await expect(input).toHaveValue("");
    await expect(
      page.getByRole("main").getByRole("complementary").getByText(message),
    ).toBeVisible();
  });
});

/**
 * Choosing who answers.
 *
 * A published agent brings its own capabilities, budget and run history; the
 * general assistant brings none of that. Picking between them is the one chat
 * control where getting it wrong means a different product answered, so the
 * choice has to be reachable, obvious and reversible.
 */
test.describe("Agent selection", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/chat");
    await page.getByRole("button", { name: "Chat controls" }).click();
    await page.getByRole("button", { name: "Agent", exact: true }).click();
  });

  test("offers the general assistant and every published agent", async ({ page }) => {
    const options = page.getByRole("radio");

    await expect(options.first()).toHaveAccessibleName(/General assistant/);
    await expect(options.first()).toHaveAttribute("aria-checked", "true");

    // The seeded agent is published, so it has to be offered by name — the
    // picker reads the agent list from the backend, and an empty picker and a
    // failed request look the same.
    await expect(page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) })).toBeVisible();
  });

  test("offers no more agents than are published", async ({ page }) => {
    // A draft has no published version, so the backend refuses to run one. The
    // seed leaves one draft and one published agent, which is what makes this
    // subtraction worth doing at all.
    await expect(page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) })).toBeVisible();
    const offered = (await page.getByRole("radio").count()) - 1; // less the assistant

    await page.goto("/agents");
    // Waited for, not counted straight away: `count()` does not retry, and an
    // agent list that has not arrived counts as an empty one.
    await expect(agentCard(page, SEEDED_AGENT_HANDLE)).toBeVisible();
    const published = await page
      .locator('a[href^="/agents/"]')
      .filter({ has: page.getByText("published", { exact: true }) })
      .count();
    const drafts = await page
      .locator('a[href^="/agents/"]')
      .filter({ has: page.getByText("draft", { exact: true }) })
      .count();

    expect(published, "the seed should leave at least one published agent").toBeGreaterThan(0);
    expect(
      drafts,
      "the seed should leave a draft, or this subtraction proves nothing",
    ).toBeGreaterThan(0);
    expect(offered).toBe(published);
  });

  test("moves the selection to the agent that was picked, and back", async ({ page }) => {
    const options = page.getByRole("radio");
    const agent = page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) });

    await agent.click();
    await expect(agent).toHaveAttribute("aria-checked", "true");
    await expect(options.first()).toHaveAttribute("aria-checked", "false");

    await options.first().click();
    await expect(options.first()).toHaveAttribute("aria-checked", "true");
  });

  test("keeps the choice across a reload", async ({ page }) => {
    await page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) }).click();
    await page.reload();

    // Surfaced on the closed trigger, not only inside the popover: the user has
    // to know who is about to answer before they type, not after they open a
    // panel they have no reason to open.
    await expect(page.getByRole("button", { name: "Chat controls" })).toContainText(
      SEEDED_AGENT_NAME,
    );
  });
});
