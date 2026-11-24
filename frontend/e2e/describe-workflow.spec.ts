import type { Page, TestInfo } from "@playwright/test";

import { expect, test } from "./fixtures";
import { AUTH_STATE, nowListed } from "./helpers";

test.use({ storageState: AUTH_STATE });

const CONVERSATIONS = "/api/conversations?limit=30&sort_by=updated_at&sort_dir=desc&hide_api=true";

/** Every text frame the page sends over its sockets: a sent chat turn is one. */
function watchSentFrames(page: Page): string[] {
  const sent: string[] = [];
  page.on("websocket", (socket) => {
    socket.on("framesent", ({ payload }) => sent.push(String(payload)));
  });
  return sent;
}

/**
 * The composer holds exactly the prompt, the prompt is off the address, and the
 * prompt reached neither the transcript nor a socket: it was written, not sent.
 */
async function expectDrafted(page: Page, prompt: string, sent: string[]) {
  const composer = page.getByRole("textbox", { name: "Type a message..." });
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveText(prompt);
  await expect(page).not.toHaveURL(/[?&]prompt=/);
  await expect(page.getByRole("main").getByText(prompt)).toHaveCount(0);
  // Written text is the composer's only copy; a second, delayed write would
  // double it, and a send would put it in a frame.
  await expect(composer).toHaveText(prompt);
  expect(sent.filter((frame) => frame.includes(prompt))).toEqual([]);
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

test.describe("Describe a workflow", () => {
  test("from the workflows list it seeds a new chat's composer once, unsent", async ({
    page,
  }, testInfo) => {
    const sent = watchSentFrames(page);
    // An existing conversation is open, so starting the new chat replaces it.
    const earlier = `E2E earlier chat ${Date.now().toString(36)}`;
    await page.goto("/chat");
    await expect(page.getByText("Live")).toBeVisible();
    const input = page.getByRole("textbox", { name: "Type a message..." });
    await expect(input).toBeEnabled();
    await input.fill(earlier);
    await page.getByRole("button", { name: "Send message" }).click();
    await expect(input).toHaveText("");
    await nowListed(page.request, CONVERSATIONS, "title", earlier);
    await expect(page).toHaveURL(/[?&]id=/);

    await page.goto("/workflows");
    const link = page.getByRole("link", { name: "Describe a workflow" });
    const href = (await link.getAttribute("href")) ?? "";
    const prompt = new URL(href, "http://console").searchParams.get("prompt") ?? "";
    expect(prompt).not.toBe("");
    sent.length = 0;
    await link.click();

    await expect(page).toHaveURL(/\/chat/);
    await expect(page.getByText("Live")).toBeVisible();
    await expectDrafted(page, prompt, sent);
    await expect(page.getByRole("main").getByText(earlier)).toHaveCount(0);
    await attachLayout(page, testInfo, "describe-from-workflows");
  });

  test("a direct /chat?new=1&prompt= seeds the composer once, unsent", async ({
    page,
  }, testInfo) => {
    const sent = watchSentFrames(page);
    const prompt = `Draft a workflow that files my receipts ${Date.now().toString(36)}`;
    await page.goto(`/chat?new=1&prompt=${encodeURIComponent(prompt)}`);
    await expect(page.getByText("Live")).toBeVisible();
    await expectDrafted(page, prompt, sent);
    await attachLayout(page, testInfo, "describe-direct");
  });
});
