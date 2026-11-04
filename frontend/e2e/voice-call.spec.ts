import type { Page, Route, WebSocketRoute } from "@playwright/test";

import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

/**
 * A voice call in /chat against a stubbed socket (#54).
 *
 * What only a browser proves: the call button reads the agent's readiness, the
 * page opens the voice socket and sends an SDP offer with no data channel, and
 * it draws the frames it is sent - captions inside the message being spoken,
 * an approval card with the exact arguments, the one-minute warning, the end.
 * No provider is reached: the voice socket and the readiness route are stubbed,
 * and RTCPeerConnection is replaced so no ICE or media leaves the machine.
 * Everything else - the seeded agent, the picker, the composer - is the product.
 */

test.use({
  storageState: AUTH_STATE,
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  },
  permissions: ["microphone"],
});

const READINESS = {
  available: true,
  unavailable: null,
  transport: "webrtc",
  provider: "openai",
  model: "gpt-realtime",
  cap_seconds: 600,
  minutes_left: 540,
  unavailable_capabilities: [],
};

const READY = {
  type: "ready",
  call_id: "c1",
  run_id: "r1",
  conversation_id: "00000000-0000-4000-8000-000000000054",
  transport: "webrtc",
  input_sample_rate: 24000,
  output_sample_rate: 24000,
  cap_seconds: 600,
  minutes_left: 540,
  resume_token: "tok1",
};

type Probe = { __dc?: boolean; __closed?: boolean };

/** A peer connection that offers audio and goes nowhere, and says whether it was closed. */
async function stubPeerConnection(page: Page): Promise<void> {
  await page.addInitScript(() => {
    class StubPc {
      ontrack: unknown = null;
      onconnectionstatechange: unknown = null;
      oniceconnectionstatechange: unknown = null;
      connectionState = "new";
      iceConnectionState = "new";
      localDescription: { type: string; sdp: string } | null = null;
      addTrack() {}
      createDataChannel() {
        (window as unknown as { __dc: boolean }).__dc = true;
      }
      async createOffer() {
        return { type: "offer", sdp: "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n" };
      }
      async setLocalDescription(description: { type: string; sdp: string }) {
        this.localDescription = description;
      }
      async setRemoteDescription() {}
      close() {
        (window as unknown as { __closed: boolean }).__closed = true;
      }
    }
    (window as unknown as { RTCPeerConnection: unknown }).RTCPeerConnection = StubPc;
  });
}

async function readiness(page: Page, body: object): Promise<void> {
  await page.route("**/api/agents/*/voice", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }),
  );
}

/** /chat with the seeded agent chosen, waiting on the composer being live. */
async function chatWithSeededAgent(page: Page): Promise<void> {
  await page.goto("/chat");
  // Exact: an agent's description saying "live in the chat" matches a substring.
  await expect(page.getByText("Live", { exact: true })).toBeAttached();
  await page.getByRole("button", { name: /^Agent:/ }).click();
  const agent = page.getByRole("radio", { name: new RegExp(SEEDED_AGENT_NAME) });
  await agent.click();
  await expect(agent).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");
  // Closed, and focus handed back to the picker: Radix returns it a beat after the
  // menu closes, and a popover opened in between is dismissed by that focus landing
  // outside it.
  await expect(agent).toBeHidden();
  await expect(page.getByRole("button", { name: /^Agent:/ })).toBeFocused();
}

test("a call shows captions, an approval with the exact arguments, a warning and its end", async ({
  page,
}) => {
  await stubPeerConnection(page);
  await readiness(page, READINESS);
  // The conversation the stubbed call names, read again as turns are saved: empty,
  // because nothing reached a real server.
  await page.route(`**/api/conversations/${READY.conversation_id}/messages*`, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, cost: null }),
    }),
  );
  let socket: WebSocketRoute | null = null;
  const sent: Record<string, unknown>[] = [];
  await page.routeWebSocket(/\/api\/v1\/ws\/voice/, (ws) => {
    socket = ws;
    ws.onMessage((message) => sent.push(JSON.parse(String(message))));
  });

  await chatWithSeededAgent(page);
  const start = page.getByRole("button", { name: "Start a voice call" });
  await expect(start).not.toHaveAttribute("aria-disabled");
  await start.click();

  // The offer: one audio stream, and no data channel either asked for or sent.
  await expect.poll(() => sent.length).toBeGreaterThan(0);
  expect(sent[0]).toMatchObject({ type: "start" });
  expect(String(sent[0]?.sdp_offer)).toContain("m=audio");
  expect(String(sent[0]?.sdp_offer)).not.toContain("m=application");
  expect(await page.evaluate(() => (window as unknown as Probe).__dc)).toBeUndefined();

  const send = (frame: object) => (socket as unknown as WebSocketRoute).send(JSON.stringify(frame));
  send({ type: "answer", sdp: "v=0" });
  send(READY);

  // The composer is the call bar now, with focus in it.
  const bar = page.getByRole("group", { name: "Voice call" });
  await expect(bar).toBeFocused();
  await expect(bar.getByText("Listening")).toBeVisible();

  // The caption arrives as the message it becomes, growing until it is final.
  send({
    type: "caption",
    role: "user",
    turn_id: "c1:1:user",
    part: 0,
    delta: "Send an invoice for 120 euros",
  });
  const captions = page.getByTestId("voice-captions-visible");
  await expect(captions).toContainText("Send an invoice for 120 euros");
  send({
    type: "caption",
    role: "user",
    turn_id: "c1:1:user",
    part: 0,
    final: "Send an invoice for 120 euros to Acme",
  });
  await expect(captions).toContainText("Send an invoice for 120 euros to Acme");

  // A call longer than the screen scrolls the transcript, never the page column
  // around it: the captions' screen-reader region once sat a transcript's height
  // down that column, and the chat's own scrolling carried the whole chat up and out.
  for (let turn = 2; turn <= 9; turn++) {
    send({
      type: "caption",
      role: "assistant",
      turn_id: `c1:${turn}:assistant`,
      part: 0,
      final: `Answer ${turn}. `.repeat(60),
    });
  }
  await expect(captions).toContainText("Answer 9.");
  await expect
    .poll(() =>
      page.evaluate(() => {
        const column = document.querySelector("main") as HTMLElement;
        return { overflow: column.scrollHeight - column.clientHeight, top: column.scrollTop };
      }),
    )
    .toEqual({ overflow: 0, top: 0 });

  // The exact arguments - "Ahmad", not what was said - with a countdown from the frame.
  send({ type: "state", state: "awaiting_approval" });
  send({
    type: "approval_required",
    id: "a1",
    tool: "send_invoice",
    args: { customer: "Ahmad", amount_eur: 120 },
    said: "Send an invoice for 120 euros to Acme",
    timeout_seconds: 60,
  });
  const card = page.getByRole("group", { name: "Approve Send Invoice?" });
  await expect(card.getByText("Ahmad", { exact: true })).toBeVisible();
  await expect(card.getByText(/You said/)).toContainText("to Acme");
  await expect(card.getByText(/Auto-deny in 0:(60|5\d)|Auto-deny in 1:00/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Show card" })).toBeVisible();
  await card.getByRole("button", { name: "Deny" }).click();
  await expect.poll(() => sent.at(-1)).toEqual({ type: "approval", id: "a1", decision: "deny" });
  send({ type: "approval_settled", id: "a1", outcome: "denied" });
  await expect(page.getByRole("group", { name: "Denied by you" })).toBeVisible();
  await expect(card).toHaveCount(0);

  send({ type: "state", state: "listening" });
  send({ type: "limit", seconds_left: 60 });
  await expect(bar.getByRole("alert")).toContainText("1 minute left in this call");
  // The strip under the bar counts down from the warning, not from the call's start.
  await expect(page.getByText(/^(1:00|0:5\d) left in this call\.$/)).toBeVisible();

  send({ type: "ended", reason: "time_limit" });
  (socket as unknown as WebSocketRoute).close();
  await expect(page.getByText("Call ended at the 10-minute limit")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start a new call" })).toBeVisible();
  // The composer is back, and the peer connection is gone.
  await expect(bar).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Type a message..." })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as Probe).__closed)).toBe(true);
});

test("the end of a call stays above the composer that comes back", async ({ page }) => {
  await stubPeerConnection(page);
  await readiness(page, READINESS);
  await page.route(`**/api/conversations/${READY.conversation_id}/messages*`, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, cost: null }),
    }),
  );
  let socket: WebSocketRoute | null = null;
  await page.routeWebSocket(/\/api\/v1\/ws\/voice/, (ws) => {
    socket = ws;
    ws.onMessage(() => {});
  });

  await chatWithSeededAgent(page);
  await page.getByRole("button", { name: "Start a voice call" }).click();
  await expect.poll(() => socket !== null).toBe(true);
  const send = (frame: object) => (socket as unknown as WebSocketRoute).send(JSON.stringify(frame));
  send({ type: "answer", sdp: "v=0" });
  send(READY);
  const bar = page.getByRole("group", { name: "Voice call" });
  await expect(bar.getByText("Listening")).toBeVisible();
  // Longer than the screen, so the transcript is scrolled to its end.
  for (let turn = 1; turn <= 8; turn++) {
    send({
      type: "caption",
      role: "assistant",
      turn_id: `c1:${turn}:assistant`,
      part: 0,
      final: `Answer ${turn}. `.repeat(60),
    });
  }
  await expect(page.getByTestId("voice-captions-visible")).toContainText("Answer 8.");
  const fromEnd = () =>
    page.getByTestId("voice-captions-visible").evaluate((node) => {
      const scroller = node.closest(".overflow-y-auto") as HTMLElement;
      return Math.round(scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight);
    });
  // While the call runs, the transcript follows its end.
  await expect.poll(fromEnd).toBeLessThanOrEqual(1);

  await bar.getByRole("button", { name: "End call" }).first().click();
  send({ type: "ended", reason: "user" });
  (socket as unknown as WebSocketRoute).close();
  const callAgain = page.getByRole("button", { name: "Call again" });
  await expect(callAgain).toBeVisible();

  // The composer is taller than the call bar it replaces. The transcript makes
  // room for it and stays at its end: measured 42px short before, with the
  // summary under the composer.
  await expect
    .poll(() =>
      callAgain.evaluate((button) => {
        const scroller = button.closest(".overflow-y-auto") as HTMLElement;
        return Math.round(scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight);
      }),
    )
    .toBeLessThanOrEqual(1);
});

test("an agent without a voice offers the button crossed out, and where to turn calls on", async ({
  page,
}) => {
  await readiness(page, {
    ...READINESS,
    available: false,
    unavailable: "no_voice",
    transport: null,
    provider: null,
    model: null,
    cap_seconds: 0,
  });
  await chatWithSeededAgent(page);
  const button = page.getByRole("button", { name: "Start a voice call" });
  await expect(button).toHaveAttribute("aria-disabled", "true");
  await button.hover();
  await expect(
    page.getByText("Calls aren't turned on for this agent", { exact: true }),
  ).toBeVisible();
  // The seeded owner may edit the agent, so the reason links to its Voice card.
  await expect(page.getByRole("link", { name: "Open in the Agent Builder" })).toHaveAttribute(
    "href",
    /\/agents\/[^/]+#agent-voice$/,
  );
});
