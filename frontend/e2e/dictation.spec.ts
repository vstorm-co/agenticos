import type { APIRequest, APIRequestContext, Page, Route } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, json } from "./helpers";

/**
 * Server dictation in the composer (#1797), in a real Chromium.
 *
 * What only a browser can prove: that `MediaRecorder` records the stream the
 * microphone opened, that the recording is posted to the dictation route, and
 * that the text it answers lands in the box - editable, focused and unsent.
 * jsdom has no `MediaRecorder` and no `getUserMedia`, so the unit suite mocks
 * exactly the part this spec exists for.
 *
 * Chromium's fake capture device stands in for a microphone: it plays a beep,
 * so the recording has sound in it and the silence hint stays away. Only the
 * agent's dictation route is stubbed - its readiness and the transcription - as
 * a test deployment has no provider key, and a green suite must not depend on
 * somebody else's uptime. Everything before it
 * is the product: the organization's settings, the composer reading them, the
 * capture, the timer.
 *
 * A failure is simulated with `route.abort`, never a stubbed 5xx: the
 * `apiFailures` net in `fixtures.ts` fails any test whose page saw one, and a
 * dropped connection is the case the strip has to survive anyway.
 */

test.use({
  storageState: AUTH_STATE,
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  },
  permissions: ["microphone"],
});

/** The speech fields this spec changes, so the teardown can put them back. */
interface SpeechSettings {
  chat_dictation: "off" | "browser" | "server";
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
}

interface OrgRow extends SpeechSettings {
  id: string;
  is_personal: boolean;
}

let orgId = "";
let original: SpeechSettings | null = null;

/**
 * An API context signed in as the seeded owner.
 *
 * `beforeAll` gets no `page` or `request` - those are per test - so it builds
 * its own from the session `auth.setup.ts` saved, against the project's own
 * base URL.
 */
async function ownerRequest(
  api: APIRequest,
  baseURL: string | undefined,
): Promise<APIRequestContext> {
  return api.newContext({ baseURL, storageState: AUTH_STATE });
}

async function patchSpeech(
  request: APIRequestContext,
  settings: Partial<SpeechSettings>,
): Promise<void> {
  const response = await request.patch(`/api/orgs/${orgId}`, { data: settings });
  expect(response.ok(), `PATCH /api/orgs/${orgId} answered ${response.status()}`).toBe(true);
}

// The suite runs one worker against one seeded organization, so switching it
// to `server` here and back afterwards leaves every other spec on `browser`.
test.beforeAll(async ({ playwright }, testInfo) => {
  const request = await ownerRequest(playwright.request, testInfo.project.use.baseURL);
  const { items } = await json<{ items: OrgRow[] }>(request, "/api/orgs");
  // The one the console selects on a fresh page: `preferredOrg` picks the
  // personal organization, which bootstrap reuses for the seed.
  const org = items.find((row) => row.is_personal) ?? items[0];
  expect(org, "the owner belongs to no organization; was bootstrap run?").toBeDefined();
  orgId = org!.id;
  original = {
    chat_dictation: org!.chat_dictation,
    speech_to_text_provider: org!.speech_to_text_provider,
    speech_to_text_model: org!.speech_to_text_model,
  };
  await patchSpeech(request, {
    chat_dictation: "server",
    speech_to_text_provider: "openai",
    speech_to_text_model: "whisper-1",
  });
  await request.dispose();
});

test.afterAll(async ({ playwright }, testInfo) => {
  if (original === null) return;
  const request = await ownerRequest(playwright.request, testInfo.project.use.baseURL);
  await patchSpeech(request, original);
  await request.dispose();
});

/**
 * The composer, once the socket is up and the microphone is the recording one.
 *
 * "Live" is the same wait `chat.spec.ts` makes. The microphone's own wait is
 * the assertion the settings landed: with `server` not yet read, or no agent
 * picked, the button carries the same name but is `aria-disabled` and explains
 * itself instead of recording.
 */
async function readyComposer(page: Page) {
  await page.goto("/chat");
  await expect(page.getByText("Live")).toBeVisible();

  const input = page.getByRole("textbox", { name: "Type a message..." });
  await expect(input).toBeEnabled();
  await expect(page.getByRole("button", { name: "Voice input" })).toBeEnabled();
  return input;
}

/** Record for at least a second: anything shorter is refused before it is sent. */
async function recordASecond(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Voice input" }).click();
  await expect(page.getByRole("timer", { name: "Recording time" })).toHaveText(/0:0[1-9]/);
  await page.getByRole("button", { name: "Stop and transcribe" }).click();
}

function transcribed(text: string) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ text }),
  };
}

/**
 * Stub the agent's dictation route: the readiness `GET` says ready, and each
 * `POST` is answered by `onPost`.
 *
 * The readiness is stubbed for the same reason the transcription is: it is
 * `ready` only where the organization holds a credential for the provider, and
 * a test deployment has no provider key.
 */
async function stubDictation(page: Page, onPost: (route: Route) => Promise<void>): Promise<void> {
  await page.route("**/api/agents/*/dictation", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          engine: "server",
          ready: true,
          server_available: true,
          max_seconds: 300,
          provider: "openai",
          format: "webm",
        }),
      });
      return;
    }
    await onPost(route);
  });
}

test.describe("Server dictation", () => {
  test("the transcript lands in the composer at the caret and is not sent", async ({ page }) => {
    const uploads: string[] = [];
    await stubDictation(page, async (route) => {
      uploads.push(route.request().headers()["content-type"] ?? "");
      await route.fulfill(transcribed("hello from the microphone"));
    });

    const composer = await readyComposer(page);
    await composer.fill("Say: please");
    // The caret after "Say:", not at the end, so appending would fail this.
    await composer.evaluate((box: HTMLTextAreaElement) => box.setSelectionRange(4, 4));
    await recordASecond(page);

    await expect(composer).toHaveValue("Say: hello from the microphone please");
    await expect(composer).toBeFocused();
    // One recording, posted as a multipart upload - the browser really recorded.
    expect(uploads).toHaveLength(1);
    expect(uploads[0]).toContain("multipart/form-data");
    // Still in the box, so still the person's to edit: a sent message would
    // have emptied it.
    await expect(page.getByRole("button", { name: "Send message" })).toBeEnabled();
  });

  test("a dropped connection keeps the recording for a retry", async ({ page }) => {
    let calls = 0;
    await stubDictation(page, async (route) => {
      calls += 1;
      if (calls === 1) await route.abort("internetdisconnected");
      else await route.fulfill(transcribed("second time lucky"));
    });

    const composer = await readyComposer(page);
    await recordASecond(page);

    // Scoped to the strip: Next's route announcer is an `alert` of its own.
    const strip = page.getByTestId("dictation-strip");
    await expect(strip.getByRole("alert")).toContainText("The server couldn't be reached.");
    await expect(composer).toHaveValue("");

    await strip.getByRole("button", { name: "Retry" }).click();
    await expect(composer).toHaveValue("second time lucky");
    expect(calls).toBe(2);
  });
});
