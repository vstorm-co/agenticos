import type { WebSocketRoute } from "@playwright/test";
import { test, expect } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME, readAppearanceAs } from "./helpers";

test.use({ storageState: AUTH_STATE });

function idFrom(value: unknown): string {
  if (!value || typeof value !== "object" || !("id" in value) || typeof value.id !== "string")
    throw new Error("Expected a persisted fixture ID");
  return value.id;
}

// Persist real messages through the authenticated backend. Only the model's socket
// frames are controlled, so geometry and replay tests need no paid model calls.
for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`inline questions preserve reading position and replay in ${theme} at ${width}px`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height: 900 });
      await readAppearanceAs(page, theme);
      await page.goto("/chat?answerer=agenticos");
      await expect(
        page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
      ).toBeVisible();
      const created = await page.request.post("/api/conversations", {
        data: { title: `Question geometry ${theme} ${width}` },
      });
      expect(created.ok()).toBe(true);
      const conversationId = idFrom(await created.json());
      try {
        for (let index = 1; index <= 6; index++) {
          const response = await page.request.post(
            `/api/conversations/${conversationId}/messages`,
            {
              data: {
                role: "user",
                content: `History fixture ${index}. ${"A paragraph to keep an earlier message on screen while later content grows. ".repeat(12)}`,
              },
            },
          );
          expect(response.ok()).toBe(true);
        }
        let socket: WebSocketRoute | undefined;
        let answerRequest: { requestId: string; answers: unknown } | undefined;
        await page.routeWebSocket(/\/api\/v1\/ws\/agent/, (connection) => {
          socket = connection;
          connection.onMessage((raw) => {
            const frame: unknown = JSON.parse(String(raw));
            if (
              frame &&
              typeof frame === "object" &&
              "type" in frame &&
              frame.type === "ask_user_response" &&
              "request_id" in frame &&
              typeof frame.request_id === "string" &&
              "answers" in frame
            )
              answerRequest = { requestId: frame.request_id, answers: frame.answers };
          });
        });
        await page.goto(`/chat?id=${conversationId}`);
        await expect(page.getByText("Live", { exact: true })).toBeVisible();
        await expect.poll(() => !!socket).toBe(true);
        const send = (type: string, data: object) => {
          if (!socket) throw new Error("Expected a connected chat socket");
          socket.send(JSON.stringify({ type, data }));
        };
        const scroller = page.locator("[data-chat-scroller]");
        const composer = page.locator(".composer-box");
        if (width === 390) {
          const actions = composer.locator(".chat-input-actions");
          const model = actions.locator("[data-chat-model]");
          await expect(model).toBeVisible();
          await expect
            .poll(async () => (await model.boundingBox())?.width ?? 0)
            .toBeGreaterThanOrEqual(180);
          const requiredControls = [
            actions.getByRole("button", { name: "Add to message", exact: true }),
            actions.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
            actions.getByRole("button", { name: "Show the files", exact: true }),
            actions.getByRole("button", { name: "Chat controls", exact: true }),
            actions.getByRole("button", { name: /^Permission mode:/ }),
            actions.getByRole("button", { name: "Usage of this conversation", exact: true }),
            model,
          ];
          // Resolve each required control through hydration rather than taking a
          // one-shot collection snapshot while its context row is changing.
          for (const control of requiredControls) {
            await expect(control).toBeVisible();
            await expect
              .poll(async () => (await control.boundingBox())?.width ?? 0)
              .toBeGreaterThanOrEqual(43.5);
            await expect
              .poll(async () => (await control.boundingBox())?.height ?? 0)
              .toBeGreaterThanOrEqual(43.5);
          }
        }
        await expect(scroller.getByText(/^History fixture 6\./)).toBeVisible();
        const draft = composer.getByRole("textbox");
        await draft.fill("Draft kept while answering");
        await scroller.hover();
        await page.mouse.wheel(0, -10000);
        const earlier = scroller.getByText(/^History fixture 1\./);
        // Visibility alone includes offscreen messages while the wheel is still settling.
        await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBe(0);
        await expect(earlier).toBeInViewport();
        const original = await earlier.boundingBox();
        const inputBefore = await composer.boundingBox();
        if (!original || !inputBefore)
          throw new Error("Expected visible reading and composer anchors");
        send("model_request_start", {});
        send("thinking_delta", { content: "Preparing two format questions." });
        send("ask_user", {
          questions: [
            {
              header: "Format",
              question: "Which format?",
              options: [{ label: "List" }, { label: "Paragraph" }],
              allow_custom: true,
            },
            {
              header: "Length",
              question: "Which length?",
              options: [{ label: "Short" }, { label: "Detailed" }],
              allow_custom: true,
            },
          ],
        });
        const question = page.locator("[data-question-pending]");
        await expect(question).toHaveCount(1);
        await expect.poll(async () => (await earlier.boundingBox())?.y).toBeCloseTo(original.y, 0);
        await expect
          .poll(async () => (await composer.boundingBox())?.y)
          .toBeCloseTo(inputBefore.y, 0);
        await expect(draft).toBeVisible();
        await expect(draft).toBeEnabled();
        await expect(draft).toHaveText("Draft kept while answering");
        await expect(
          page.getByRole("button", { name: "Answer the agent’s question", exact: true }),
        ).toHaveCount(0);
        await question.scrollIntoViewIfNeeded();
        await expect(question).toBeInViewport();
        const revealed = await question.boundingBox();
        if (!revealed) throw new Error("Expected the question after scrolling");
        const expectQuestionStill = async () => {
          await expect
            .poll(async () => (await question.boundingBox())?.y)
            .toBeCloseTo(revealed.y, 0);
        };
        await question.getByRole("button", { name: /^1\s*List$/ }).click();
        await expectQuestionStill();
        await question.getByRole("button", { name: /^1\s*Short$/ }).click();
        await expectQuestionStill();
        await question.getByRole("button", { name: "Send answers", exact: true }).click();
        await expect(question.getByRole("status")).toHaveText("Sending your answers…");
        await expect(
          question.getByRole("button", { name: "Send answers", exact: true }),
        ).toBeDisabled();
        await expect.poll(() => !!answerRequest).toBe(true);
        if (!answerRequest) throw new Error("Expected a correlated answer submission");
        expect(answerRequest.answers).toEqual([
          { answer: "", selected: ["List"], skipped: false },
          { answer: "", selected: ["Short"], skipped: false },
        ]);
        const saved = await page.request.post(`/api/conversations/${conversationId}/messages`, {
          data: {
            role: "assistant",
            content: "A short list is selected.",
            thinking: "Preparing two format questions.",
            parts: [
              { type: "thinking", text: "Preparing two format questions." },
              { type: "ask_user", question: "Which format?", answer: "List" },
              { type: "ask_user", question: "Which length?", answer: "Short" },
              { type: "text", text: "A short list is selected." },
            ],
          },
        });
        expect(saved.ok()).toBe(true);
        const messageId = idFrom(await saved.json());
        send("ask_user_answered", { request_id: answerRequest.requestId });
        send("final_result", { output: "A short list is selected." });
        send("message_saved", { message_id: messageId });
        send("complete", {});
        await expect(page.locator("[data-question-pending]")).toHaveCount(0);
        const receipt = page.locator("[data-chat-question]");
        await expect.poll(async () => (await receipt.boundingBox())?.y).toBeCloseTo(revealed.y, 0);
        await expect(receipt).toContainText("List");
        await expect(receipt).toContainText("Short");
        await expect(page.getByRole("button", { name: /Thought/ }).first()).toHaveAttribute(
          "aria-expanded",
          "false",
        );
        await expect
          .poll(async () => (await composer.boundingBox())?.y)
          .toBeCloseTo(inputBefore.y, 0);
        await page.reload();
        await expect(page.getByText("A short list is selected.", { exact: true })).toBeVisible();
        await expect(page.locator("[data-chat-question]")).toHaveCount(1);
        await expect(receipt).toContainText("List");
        await expect(receipt).toContainText("Short");
        await expect(page.locator("[data-question-pending]")).toHaveCount(0);
        await expect(page.getByRole("button", { name: /Thought/ }).first()).toHaveAttribute(
          "aria-expanded",
          "false",
        );
        await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /\blight\b/);
      } finally {
        const removed = await page.request.delete(`/api/conversations/${conversationId}`);
        expect(removed.ok()).toBe(true);
      }
    });
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`short phone home keeps both Inbox rows and full composer visible in ${theme}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 725 });
    await readAppearanceAs(page, theme);
    await page.route("**/api/branding/notice", (route) =>
      route.fulfill({
        json: {
          message: "Short phone announcement",
          level: "info",
          maintenance_mode: false,
          maintenance_message: null,
        },
      }),
    );
    let showInbox = true;
    await page.route("**/api/me/suggestions", (route) =>
      route.fulfill({
        json: {
          items: (showInbox ? [1, 2] : []).map((number) => ({
            id: `00000000-0000-4000-8000-00000000000${number}`,
            kind: "finding",
            status: "open",
            title: `Review useful Inbox finding ${number}`,
            detail: "A compact mobile finding",
            payload: {},
            urgent: number === 1,
            created_at: "2026-11-21T09:00:00Z",
          })),
          total: showInbox ? 2 : 0,
        },
      }),
    );
    for (const endpoint of ["approvals", "workflow-approvals"]) {
      await page.route(`**/api/${endpoint}?*`, (route) =>
        route.fulfill({ json: { items: [], total: 0 } }),
      );
    }
    await page.route("**/api/users/me/console-experience", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      const body: unknown = await response.json();
      if (!body || typeof body !== "object" || Array.isArray(body))
        throw new Error("Expected membership console preferences");
      await route.fulfill({
        response,
        json: {
          ...body,
          effective: {
            inbox: true,
            starters: true,
            greeting: true,
            feature_hints: true,
          },
        },
      });
    });
    await page.goto("/chat");
    await expect(page.getByText("Short phone announcement", { exact: true })).toBeVisible();
    const inbox = page.locator(".chat-home-inbox");
    await expect(inbox).toHaveAttribute("aria-busy", "false");
    await expect(inbox.locator("li")).toHaveCount(2);
    const model = page.locator("[data-chat-model]");
    await expect(model).toBeVisible();
    const composer = page.locator(".composer-box");
    await expect
      .poll(async () => {
        const box = await composer.boundingBox();
        return box ? box.y >= 0 && box.y + box.height <= 725 : false;
      })
      .toBe(true);
    const modelBox = await model.boundingBox();
    expect(modelBox?.width).toBeGreaterThanOrEqual(180);
    expect(modelBox?.height).toBeGreaterThanOrEqual(43.5);
    const populated = await composer.boundingBox();
    showInbox = false;
    await page.reload();
    await expect(inbox).toHaveAttribute("aria-hidden", "true");
    await expect(inbox).toBeEmpty();
    await expect(page.getByRole("link", { name: "Open inbox", exact: true })).toHaveCount(0);
    await expect
      .poll(async () => (await composer.boundingBox())?.y)
      .toBeCloseTo(populated?.y ?? -1, 0);
    const before = await composer.boundingBox();
    await page.getByRole("textbox", { name: "Type a message..." }).fill("An editable draft");
    expect((await composer.boundingBox())?.y).toBeCloseTo(before?.y ?? -1, 0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);
  });
}
