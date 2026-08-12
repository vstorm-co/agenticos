import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, DRAFT_AGENT_NAME, openAgent, openBuilderTab } from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * Publishing a surface, editing it, and what a stranger then gets.
 *
 * `journey.spec.ts` already proves the one claim the surface rests on: a link
 * published from the Builder, opened signed into nothing, answers with the token
 * the *published version* was told to say. What it does not cover is everything
 * after publishing - editing a live surface, giving a page a picture, and the two
 * controls the page offers a visitor - and each of those is a write that a panel
 * can appear to make without making.
 *
 * So every assertion here survives a reload. A form that only looks right until
 * the next fetch is a form that stored nothing, and the refetch after a write is
 * sometimes answered with the pre-write list (#230), which is why the reload is
 * explicit rather than implied.
 *
 * The draft agent, not the seeded one: `sharing.spec.ts` writes to the seeded
 * agent's Availability tab, and two specs editing one row pass or fail on
 * whichever worker got there first.
 */

async function openAvailability(page: Page, agent: string): Promise<Locator> {
  await openAgent(page, agent);
  await openBuilderTab(page, "Availability");
  return page.getByRole("tabpanel");
}

/** Publish a hosted page, and answer with the link it produced. */
async function publishPage(page: Page, panel: Locator): Promise<string> {
  const publish = panel.getByRole("button", { name: /Hosted page/ }).first();
  if (!(await publish.isVisible())) {
    test.skip(true, "this user cannot publish an embed");
  }
  await publish.click();
  await panel.getByRole("button", { name: "Publish" }).click();

  await page.reload();
  await openBuilderTab(page, "Availability");
  const origin = new URL(page.url()).origin;
  const link = page.getByText(new RegExp(`^${origin}/e/`)).first();
  await expect(link).toBeVisible({ timeout: 30_000 });
  return (await link.textContent())?.trim() ?? "";
}

test.describe("A published surface", () => {
  test("is editable after it exists, and the change survives a reload", async ({ page }) => {
    const panel = await openAvailability(page, DRAFT_AGENT_NAME);
    await publishPage(page, panel);

    await panel
      .getByRole("button", { name: /^Edit / })
      .first()
      .click();
    const title = panel.getByLabel("Page title");
    await title.fill("Refund questions");
    // Every switch here is a filter on what the server *sends*, so the one worth
    // driving end to end is the one whose default is on: turning the narration
    // off has to reach the row rather than the renderer.
    await panel.getByRole("checkbox", { name: /What the agent is doing/ }).click();
    await panel.getByRole("button", { name: "Save changes" }).click();

    await page.reload();
    await openBuilderTab(page, "Availability");
    await panel
      .getByRole("button", { name: /^Edit / })
      .first()
      .click();
    await expect(panel.getByLabel("Page title")).toHaveValue("Refund questions");
    await expect(
      panel.getByRole("checkbox", { name: /What the agent is doing/ }),
    ).not.toBeChecked();
  });

  test("takes a picture of its own once it exists", async ({ page }) => {
    // The upload needs a row to attach to, which is why the option is offered
    // and disabled while a page is being published rather than hidden. Here the
    // page exists, so the picker is reachable and the button says "Replace" once
    // a file has landed - which is the only visible proof the write happened.
    const panel = await openAvailability(page, DRAFT_AGENT_NAME);
    await publishPage(page, panel);
    await panel
      .getByRole("button", { name: /^Edit / })
      .first()
      .click();

    await panel.getByLabel("Logo").click();
    await page.getByRole("option", { name: "A picture you upload" }).click();
    await panel.locator('input[type="file"]').setInputFiles({
      name: "logo.png",
      mimeType: "image/png",
      // The smallest valid PNG: one transparent pixel. The upload path checks
      // the MIME type and the size, not what the image looks like.
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
        "base64",
      ),
    });

    await expect(panel.getByRole("button", { name: "Replace the picture" })).toBeVisible({
      timeout: 30_000,
    });
  });
});

test.describe("What the page offers a visitor", () => {
  test("starts a fresh thread without losing the link", async ({ page, browser }) => {
    // A new thread is a new continuity key, so what has to be true is both
    // halves: what was on screen is gone, and the same URL still works. A page
    // that cleared the thread and then could not reconnect would look identical
    // for exactly as long as nobody typed again.
    const panel = await openAvailability(page, DRAFT_AGENT_NAME);
    const hostedUrl = await publishPage(page, panel);

    const stranger = await browser.newContext();
    const hosted = await stranger.newPage();
    try {
      await hosted.goto(hostedUrl);
      const ask = hosted.getByRole("textbox", { name: "Ask a question…" });
      await expect(ask).toBeEnabled({ timeout: 30_000 });
      // A fresh context has consented to nothing, which used to put the cookie
      // banner over the composer: `fixed bottom-4 right-4` against a page whose
      // bottom row is the composer, so Send and the microphone were unclickable
      // for thirty seconds of `subtree intercepts pointer events` (#644). Asserted
      // rather than left to the click, which only fails when the viewport happens
      // to be the narrow one.
      await expect(hosted.getByRole("dialog", { name: "We use cookies" })).toHaveCount(0);
      await ask.fill("Remember this.");
      await hosted.getByRole("button", { name: "Send" }).click();
      await expect(hosted.getByText("Remember this.")).toBeVisible();

      const before = await hosted.evaluate(() =>
        Object.entries(window.localStorage).find(([key]) => key.startsWith("agenticos:visitor:")),
      );

      await hosted.getByRole("button", { name: "New chat" }).click();

      await expect(hosted.getByText("Remember this.")).toHaveCount(0);
      const after = await hosted.evaluate(() =>
        Object.entries(window.localStorage).find(([key]) => key.startsWith("agenticos:visitor:")),
      );
      expect(after).not.toEqual(before);
      await expect(hosted.getByRole("textbox", { name: "Ask a question…" })).toBeEnabled();
    } finally {
      await stranger.close();
    }
  });

  test("offers dictation only where the operator turned it on", async ({ page, browser }) => {
    // Two halves, and the second is the reason this is an end-to-end test rather
    // than a unit one: the control is gated on the *browser* having a recogniser
    // as well as on the operator allowing it, and only a real browser can answer
    // the first. Whether this one has one is not ours to decide, so the
    // assertion is written against what it reports.
    const panel = await openAvailability(page, DRAFT_AGENT_NAME);
    const hostedUrl = await publishPage(page, panel);
    await panel
      .getByRole("button", { name: /^Edit / })
      .first()
      .click();
    await panel.getByRole("checkbox", { name: /A microphone in the composer/ }).click();
    await panel.getByRole("button", { name: "Save changes" }).click();

    const stranger = await browser.newContext();
    const hosted = await stranger.newPage();
    try {
      await hosted.goto(hostedUrl);
      await expect(hosted.getByRole("textbox", { name: "Ask a question…" })).toBeEnabled({
        timeout: 30_000,
      });
      const hasRecogniser = await hosted.evaluate(
        () => "SpeechRecognition" in window || "webkitSpeechRecognition" in window,
      );
      const dictate = hosted.getByRole("button", { name: "Dictate" });

      if (!hasRecogniser) {
        // Not a skip: a browser without one being shown no microphone is the
        // behaviour, and it is the half that is easy to get wrong by rendering a
        // button that does nothing.
        await expect(dictate).toHaveCount(0);
        return;
      }
      await expect(dictate).toBeVisible();
      await dictate.click();
      await expect(hosted.getByRole("button", { name: "Stop dictating" })).toBeVisible();
    } finally {
      await stranger.close();
    }
  });
});
