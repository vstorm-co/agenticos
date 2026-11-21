import { createTranslator } from "next-intl";
import { expect, it } from "vitest";
import en from "../../messages/en.json";
import pl from "../../messages/pl.json";
import de from "../../messages/de.json";
import tr from "../../messages/tr.json";
import type { Suggestion } from "./suggestions-api";
import { suggestionChatPrompt } from "./suggestion-chat-prompt";

const item: Suggestion = {
  id: "private-id",
  kind: "agent",
  status: "open",
  title: "Support assistant",
  detail: "Answer customer questions from the help center.",
  payload: {},
  created_at: "2026-11-21T10:00:00Z",
};
const t = createTranslator({ locale: "en", messages: en.inbox.chatDraft });

it("prefers the actual generated request, trimmed, without rewriting its intent", () => {
  expect(
    suggestionChatPrompt(
      {
        ...item,
        payload: { chat_prompt: "  Create a support agent with our help center knowledge.  " },
      },
      t,
    ),
  ).toBe("Create a support agent with our help center knowledge.");
});
it("uses actionable legacy fields, topic, detail and routine schedule", () => {
  expect(
    suggestionChatPrompt(
      {
        ...item,
        kind: "routine",
        payload: {
          chat_prompt: " \n ",
          prompt: "Summarize unanswered tickets",
          cron: "0 9 * * 1-5",
        },
      },
      t,
    ),
  ).toBe(
    "Help me set up this routine: Summarize unanswered tickets\n\nTopic: Support assistant\n\nAnswer customer questions from the help center.\n\nSuggested schedule (cron): 0 9 * * 1-5",
  );
  expect(
    suggestionChatPrompt({ ...item, payload: { request: "Draft the help center agent" } }, t),
  ).toContain("Help me create an agent for this request: Draft the help center agent");
});
it.each([null, [], { chat_prompt: {}, request: 42, prompt: false, cron: ["bad"] }])(
  "ignores unsafe unknown payload values: %j",
  (payload) => {
    const input = { ...item, payload };
    // Stored JSON may predate the current payload shape; this is the read boundary.
    expect(suggestionChatPrompt(input, t)).toBe(
      "Help me create an agent for this request: Support assistant\n\nAnswer customer questions from the help center.",
    );
  },
);
for (const [locale, messages] of Object.entries({ en, pl, de, tr })) {
  const translated = createTranslator({ locale, messages: messages.inbox.chatDraft });
  for (const kind of ["agent", "routine", "finding", "profile", "role_pack"] as const) {
    it(`provides a concrete ${kind} draft in ${locale} without an internal identifier`, () => {
      const draft = suggestionChatPrompt({ ...item, kind }, translated);
      expect(draft).toContain(item.title);
      expect(draft).toContain(item.detail);
      expect(draft).not.toContain(item.id);
      expect(draft).not.toContain("{text}");
    });
  }
}

it("does not repeat the same title or request as a detail paragraph", () => {
  expect(suggestionChatPrompt({ ...item, detail: item.title }, t)).toBe(
    "Help me create an agent for this request: Support assistant",
  );
  expect(
    suggestionChatPrompt(
      { ...item, detail: "Build a support agent", payload: { request: "Build a support agent" } },
      t,
    ),
  ).toBe(
    "Help me create an agent for this request: Build a support agent\n\nTopic: Support assistant",
  );
});
