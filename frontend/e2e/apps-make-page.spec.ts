import type { Page, TestInfo } from "@playwright/test";

import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

const PROMPT = "Build me a page that…";

/** Every socket frame and non-GET request body the page sends: a sent chat turn is one. */
function watchSentFrames(page: Page): string[] {
  const sent: string[] = [];
  page.on("websocket", (socket) => {
    socket.on("framesent", ({ payload }) => sent.push(String(payload)));
  });
  page.on("request", (request) => {
    if (request.method() !== "GET") sent.push(request.postData() ?? "");
  });
  return sent;
}

async function attachLayout(page: Page, testInfo: TestInfo, name: string) {
  for (const [label, size] of [
    ["desktop", { width: 1280, height: 800 }],
    ["mobile", { width: 390, height: 844 }],
  ] as const) {
    await page.setViewportSize(size);
    await testInfo.attach(`${name}-${label}`, {
      body: await page.screenshot(),
      contentType: "image/png",
    });
  }
}

test.describe("Make a page from /apps", () => {
  test("the entry opens a new chat with the prompt in the composer once, unsent", async ({
    page,
  }, testInfo) => {
    const sent = watchSentFrames(page);
    await page.goto("/apps");
    const entry = page.getByRole("button", { name: "Make a page" }).first();
    await expect(entry).toBeVisible();
    await attachLayout(page, testInfo, "apps-entry");
    await page.setViewportSize({ width: 1280, height: 800 });
    await entry.click();

    await expect(page).toHaveURL(/\/chat/);
    await expect(page.getByText("Live")).toBeVisible();
    const composer = page.getByRole("textbox", { name: "Type a message..." });
    await expect(composer).toBeEnabled();
    await expect(composer).toHaveText(PROMPT);
    await expect(page).not.toHaveURL(/[?&]prompt=/);
    await expect(page.locator("[data-transcript]").getByText(PROMPT)).toHaveCount(0);
    // A second, delayed write would double the text; a send would put it in a frame and the transcript.
    await expect(composer).toHaveText(PROMPT);
    expect(sent.filter((frame) => frame.includes(PROMPT))).toEqual([]);
    await attachLayout(page, testInfo, "apps-entry-chat");
  });
});
