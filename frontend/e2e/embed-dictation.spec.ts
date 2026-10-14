import type {
  APIRequest,
  APIRequestContext,
  Browser,
  BrowserContext,
  Page,
} from "@playwright/test";

import { expect, test } from "./fixtures";

import { AUTH_STATE, json, SEEDED_AGENT_NAME } from "./helpers";

/**
 * Server dictation on a hosted page and in the website widget (#1797), in a
 * real Chromium.
 *
 * What only a browser can prove: that the page and the plain-JS widget record
 * the microphone the visitor opened, post it to the embed's own `/dictation`
 * route, and put the text into the box - editable and unsent. jsdom has neither
 * `MediaRecorder` nor `getUserMedia`, and the widget has no unit runtime at all.
 *
 * **The configs are the product, and only the transcription is stubbed.** A
 * hosted page reads its config server-side, so no browser route can fake it:
 * the organization is pointed at a provider here and given a vault key for it,
 * which is what makes the public config say `server`. The key is a throwaway
 * string and nothing reaches the provider - the `POST` is answered by
 * `page.route` - so a green run depends on nobody's uptime. Groq, not OpenAI, so
 * a deployment whose real OpenAI key this organization uses is left alone; the
 * settings and the key are put back afterwards.
 *
 * The widget needs a site to run on, and an allowed origin to be admitted from.
 * `page.route` serves a two-line page at `https://shop.e2e.test` - HTTPS, so the
 * browser will open a microphone there - and the embed is published with that
 * origin on its list. The widget's own script, config and socket are the real
 * backend's.
 *
 * Chrome's local network access check is switched off for this file: a page
 * `page.route` fulfils counts as public whatever its host, and a public page
 * loading a script from a backend on loopback is refused before the widget
 * runs. A real customer site and a real deployment are both public, so the
 * check guards nothing here that production has.
 */

const SITE = "https://shop.e2e.test";

test.use({
  storageState: AUTH_STATE,
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests",
    ],
  },
  permissions: ["microphone"],
});

interface SpeechPair {
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
  speech_to_text_secret_id: string | null;
}

interface OrgRow extends SpeechPair {
  id: string;
  is_personal: boolean;
}

interface EmbedRow {
  id: string;
  public_key: string;
  snippet: string | null;
  page_url: string | null;
}

let orgId = "";
let original: SpeechPair | null = null;
let secretId: string | null = null;
let agentId: string | null = null;
const published: string[] = [];

async function ownerRequest(
  api: APIRequest,
  baseURL: string | undefined,
): Promise<APIRequestContext> {
  return api.newContext({ baseURL, storageState: AUTH_STATE });
}

async function patchSpeech(request: APIRequestContext, pair: SpeechPair): Promise<void> {
  const response = await request.patch(`/api/orgs/${orgId}`, { data: pair });
  expect(response.ok(), `PATCH /api/orgs/${orgId} answered ${response.status()}`).toBe(true);
}

test.beforeAll(async ({ playwright }, testInfo) => {
  const request = await ownerRequest(playwright.request, testInfo.project.use.baseURL);
  const { items } = await json<{ items: OrgRow[] }>(request, "/api/orgs");
  const org = items.find((row) => row.is_personal) ?? items[0];
  expect(org, "the owner belongs to no organization; was bootstrap run?").toBeDefined();
  orgId = org!.id;
  original = {
    speech_to_text_provider: org!.speech_to_text_provider,
    speech_to_text_model: org!.speech_to_text_model,
    speech_to_text_secret_id: org!.speech_to_text_secret_id,
  };

  // The organization's pair is saved with its key named beside it.
  const secret = await request.post("/api/secrets", {
    data: {
      name: `e2e-embed-dictation-${Date.now().toString(36)}`,
      value: { kind: "api_key", api_key: "gsk_e2eNOTAREALKEYatallZZ99" },
      purpose: "groq",
      visibility: "org",
    },
  });
  expect(secret.ok(), `POST /api/secrets answered ${secret.status()}`).toBe(true);
  secretId = ((await secret.json()) as { id: string }).id;
  await patchSpeech(request, {
    speech_to_text_provider: "groq",
    speech_to_text_model: "whisper-large-v3-turbo",
    speech_to_text_secret_id: secretId,
  });

  // Published, because a recording for an agent nobody runs is refused - and
  // its public config says `off` - before anything is paid for.
  const agents = await json<{
    items: { id: string; name: string; current_version_id: string | null }[];
  }>(request, "/api/agents");
  agentId =
    agents.items.find(
      (agent) => agent.name === SEEDED_AGENT_NAME && agent.current_version_id !== null,
    )?.id ?? null;
  await request.dispose();
});

test.afterAll(async ({ playwright }, testInfo) => {
  const request = await ownerRequest(playwright.request, testInfo.project.use.baseURL);
  for (const id of published) await request.delete(`/api/agents/embeds/${id}`);
  // The settings first: they name the key, which goes after.
  if (original !== null) await patchSpeech(request, original);
  if (secretId !== null) await request.delete(`/api/secrets/${secretId}`);
  await request.dispose();
});

/** Publish the seeded agent on one surface with server dictation, through the API. */
async function publish(page: Page, config: Record<string, unknown>, origins: string[] = []) {
  test.skip(agentId === null, `${SEEDED_AGENT_NAME} has no published version here`);
  const response = await page.request.post("/api/agents/embeds", {
    data: {
      agent_id: agentId,
      name: `e2e voice ${Date.now().toString(36)}`,
      config: { ...config, dictation: "server" },
      allowed_origins: origins,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const embed = (await response.json()) as EmbedRow;
  published.push(embed.id);
  return embed;
}

/**
 * Answer the embed's `/dictation` with `text`, as the provider would have.
 *
 * With the CORS header the real route sends: the page and the widget both post
 * across origins, and a browser hides a response that does not name theirs.
 */
async function transcribeAs(context: BrowserContext, origin: string, text: string) {
  const posted: string[] = [];
  await context.route("**/api/v1/embed/*/dictation", async (route) => {
    posted.push(route.request().headers()["content-type"] ?? "");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": origin, vary: "Origin" },
      body: JSON.stringify({ text }),
    });
  });
  return posted;
}

/** A visitor: signed into nothing, with the microphone allowed. */
async function stranger(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({ permissions: ["microphone"] });
}

test.describe("Server dictation for a visitor", () => {
  test("a hosted page records, posts to its own route and fills the box", async ({
    page,
    browser,
  }) => {
    const embed = await publish(page, { kind: "page" });
    const visitor = await stranger(browser);
    try {
      const hosted = await visitor.newPage();
      const posted = await transcribeAs(
        visitor,
        new URL(embed.page_url!).origin,
        "where is my refund",
      );
      await hosted.goto(embed.page_url!);
      const box = hosted.getByRole("textbox", { name: "Ask a question…" });
      await expect(box).toBeEnabled({ timeout: 30_000 });

      await hosted.getByRole("button", { name: "Dictate" }).click();
      await expect(hosted.getByRole("timer", { name: "Recording time" })).toHaveText(/0:0[1-9]/);
      await hosted.getByRole("button", { name: "Stop and transcribe" }).click();

      await expect(box).toHaveValue("where is my refund");
      expect(posted).toHaveLength(1);
      expect(posted[0]).toContain("multipart/form-data");
      // Still the visitor's to edit: a sent message would have emptied the box.
      await expect(hosted.getByRole("button", { name: "Send" })).toBeEnabled();
    } finally {
      await visitor.close();
    }
  });

  test("the widget on an allowed site records and fills its own box", async ({ page, browser }) => {
    const embed = await publish(page, { kind: "widget" }, [SITE]);
    const visitor = await stranger(browser);
    try {
      await visitor.route(`${SITE}/`, (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/html",
          body: `<!doctype html><html><body><h1>Shop</h1>${embed.snippet}</body></html>`,
        }),
      );
      const posted = await transcribeAs(visitor, SITE, "do you ship to Poland");
      const site = await visitor.newPage();
      await site.goto(`${SITE}/`);

      await site.getByRole("button", { name: "Chat" }).click();
      await site.getByRole("button", { name: "Dictate" }).click();
      const stop = site.getByRole("button", { name: "Stop and transcribe" });
      await expect(stop).toBeVisible();
      // Past the one-second floor, below which nothing is sent.
      await expect(site.getByText(/^0:0[1-9]$/)).toBeVisible();
      await stop.click();

      await expect(site.getByPlaceholder("Type your message…")).toHaveValue(
        "do you ship to Poland",
      );
      expect(posted).toHaveLength(1);
    } finally {
      await visitor.close();
    }
  });
});
