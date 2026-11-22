import type { Suggestion } from "./suggestions-api";

type DraftKey = Suggestion["kind"] | "topic" | "schedule";
type TranslateDraft = (key: DraftKey, values: { text: string }) => string;

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function field(payload: unknown, key: string): string | null {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return null;
  return text(Object.getOwnPropertyDescriptor(payload, key)?.value);
}

/** Draft only: a proposal's actual request is editable before any action is sent. */
export function suggestionChatPrompt(
  suggestion: Omit<Suggestion, "payload"> & { payload: unknown },
  t: TranslateDraft,
): string {
  const generated = field(suggestion.payload, "chat_prompt");
  if (generated) return generated;
  const title = suggestion.title.trim();
  const request =
    field(suggestion.payload, "request") ?? field(suggestion.payload, "prompt") ?? title;
  const detail = text(suggestion.detail);
  const cron = field(suggestion.payload, "cron");
  return [
    t(suggestion.kind, { text: request }),
    request !== title && title ? t("topic", { text: title }) : null,
    detail && detail !== request && detail !== title ? detail : null,
    suggestion.kind === "routine" && cron ? t("schedule", { text: cron }) : null,
  ]
    .filter((part) => part !== null)
    .join("\n\n");
}
