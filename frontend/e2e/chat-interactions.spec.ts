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
      await page.goto("/chat");
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
        await expect(scroller.getByText(/^History fixture 6\./)).toBeVisible();
        await scroller.hover();
        await page.mouse.wheel(0, -10000);
        const earlier = scroller.getByText(/^History fixture 1\./);
        await expect(earlier).toBeVisible();
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
        await page
          .getByRole("button", { name: "Answer the agent’s question", exact: true })
          .click();
        const inset = await scroller.evaluate((element) => ({
          top: element.getBoundingClientRect().top,
          padding: Number.parseFloat(getComputedStyle(element).scrollPaddingTop) || 24,
        }));
        await test.info().attach("question-reveal-geometry", {
          body: Buffer.from(
            JSON.stringify(
              await scroller.evaluate((element) => {
                const card = element.querySelector("[data-question-pending]");
                return {
                  scrollTop: element.scrollTop,
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight,
                  scrollerTop: element.getBoundingClientRect().top,
                  questionTop: card?.getBoundingClientRect().top,
                  documentScroll: document.scrollingElement?.scrollTop,
                  focusedRole: document.activeElement?.getAttribute("role"),
                  focusedLabel: document.activeElement?.getAttribute("aria-label"),
                };
              }),
            ),
          ),
          contentType: "application/json",
        });
        await expect
          .poll(async () => (await question.boundingBox())?.y)
          .toBeCloseTo(inset.top + inset.padding, 0);
        const revealed = await question.boundingBox();
        if (!revealed) throw new Error("Expected the explicitly revealed question");
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
