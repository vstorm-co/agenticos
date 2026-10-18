import type { APIRequest, APIRequestContext, Page, Route } from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, json } from "./helpers";

/**
 * Server dictation in the composer (#1797), in a real Chromium.
 *
 * What only a browser can prove: that the recorder captures the stream the
 * microphone opened, that the recording is posted to the dictation route, and
 * that the text it answers lands in the box - editable, focused and unsent.
 * jsdom has no Web Audio and no `getUserMedia`, so the unit suite mocks
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
  speech_to_text_secret_id: string | null;
  dictation_max_seconds: number;
}

interface OrgRow extends SpeechSettings {
  id: string;
  is_personal: boolean;
}

let orgId = "";
let original: SpeechSettings | null = null;
let secretId: string | null = null;

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
    speech_to_text_secret_id: org!.speech_to_text_secret_id,
    dictation_max_seconds: org!.dictation_max_seconds,
  };
  // A pair is saved with a key named beside it - an organization-wide one for
  // its provider. Never used: the transcription is stubbed.
  const secret = await request.post("/api/secrets", {
    data: {
      name: `e2e-dictation-${Date.now().toString(36)}`,
      value: { kind: "api_key", api_key: "sk-e2eNOTAREALKEYatallZZ99" },
      purpose: "openai",
      visibility: "org",
    },
  });
  expect(secret.ok(), `POST /api/secrets answered ${secret.status()}`).toBe(true);
  secretId = ((await secret.json()) as { id: string }).id;
  // The shortest limit an organization may set, so the auto-stop is reached
  // in a test; the other recordings here last a second.
  await patchSpeech(request, {
    chat_dictation: "server",
    speech_to_text_provider: "openai",
    speech_to_text_model: "whisper-1",
    speech_to_text_secret_id: secretId,
    dictation_max_seconds: 10,
  });
  await request.dispose();
});

test.afterAll(async ({ playwright }, testInfo) => {
  const request = await ownerRequest(playwright.request, testInfo.project.use.baseURL);
  // The settings first: they may name the key, which goes after.
  if (original !== null) await patchSpeech(request, original);
  if (secretId !== null) await request.delete(`/api/secrets/${secretId}`);
  await request.dispose();
});

/**
 * The composer, once the socket is up and the microphone is the recording one.
 *
 * "Live" is the same wait `chat.spec.ts` makes. The microphone's own wait is
 * the assertion the settings landed: with `server` not yet read, or no agent
 * picked, the `+` offers no voice input and the composer explains why instead.
 */
async function readyComposer(page: Page) {
  await page.goto("/chat");
  await expect(page.getByText("Live")).toBeVisible();

  const input = page.getByRole("textbox", { name: "Type a message..." });
  await expect(input).toBeEnabled();
  await page.getByRole("button", { name: "Add to message" }).click();
  await expect(page.getByRole("menuitem", { name: /Voice input/ })).toBeVisible();
  await page.keyboard.press("Escape");
  return input;
}

/** Start recording from the composer's `+`, where the microphone lives. */
async function startDictating(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Add to message" }).click();
  await page.getByRole("menuitem", { name: /Voice input/ }).click();
}

/** Record for at least a second: anything shorter is refused before it is sent. */
async function recordASecond(page: Page): Promise<void> {
  await startDictating(page);
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
 * `ready` only where a usable key is named beside the pair, and the key this
 * spec stores is not one any provider would accept.
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
          unavailable: null,
          max_seconds: 300,
          provider: "openai",
          // The default every deployment starts on: Web Audio samples written
          // as 16 kHz mono PCM WAV, not `MediaRecorder`'s WebM.
          format: "wav",
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
    const bodies: string[] = [];
    await stubDictation(page, async (route) => {
      uploads.push(route.request().headers()["content-type"] ?? "");
      bodies.push(route.request().postDataBuffer()?.toString("latin1") ?? "");
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
    // As the readiness said: a WAV file of 16 kHz mono 16-bit PCM, which is all
    // the server accepts unless the deployment has turned compressed audio on.
    expect(bodies[0]).toContain("Content-Type: audio/wav");
    expect(bodies[0]).toMatch(/RIFF[\s\S]{4}WAVEfmt /);
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

  test("stops itself at the limit, says so while transcribing, then says what landed", async ({
    page,
  }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await stubDictation(page, async (route) => {
      await held;
      await route.fulfill(transcribed("three words here"));
    });

    const composer = await readyComposer(page);
    await startDictating(page);

    // Nothing is pressed: the organization's 10 s limit stops it.
    const strip = page.getByTestId("dictation-strip");
    await expect(strip).toContainText("Stopped at the 0:10 limit.", { timeout: 15_000 });
    release();

    await expect(composer).toHaveValue("three words here");
    await expect(strip).toContainText("Inserted 3 words");
    // The next key is the person moving on, and the note goes with it.
    await composer.press("End");
    await expect(strip).not.toContainText("Inserted");
  });
});
