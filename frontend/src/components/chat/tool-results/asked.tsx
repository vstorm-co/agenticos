"use client";

import { useTranslations } from "next-intl";

import type { ToolCall } from "@/types";

/** One question as the step shows it, and what the person chose. */
export interface AskedQuestion {
  header: string;
  question: string;
  answer: string[] | null;
}

/**
 * The questions an `ask_user_question` call put, paired with the answers it got.
 *
 * The arguments hold the questions, each under a short `header`; the result maps
 * that header to the labels chosen (a list) or the words typed (a string). A
 * question with no entry in the result has not been answered yet - the run is
 * still waiting on it. Null when the arguments are not a question list, so the
 * step falls back to the generic view rather than drawing nothing.
 */
export function parseAsked(toolCall: ToolCall): AskedQuestion[] | null {
  const questions = (toolCall.args as { questions?: unknown }).questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;
  const answers = toRecord(toolCall.result);
  return questions.flatMap((raw) => {
    if (raw === null || typeof raw !== "object") return [];
    const { header, question } = raw as { header?: unknown; question?: unknown };
    if (typeof question !== "string") return [];
    const key = typeof header === "string" ? header : question;
    const given = answers?.[key];
    const answer = Array.isArray(given)
      ? given.map(String)
      : typeof given === "string" && given.trim() !== ""
        ? [given.trim()]
        : null;
    return [{ header: typeof header === "string" ? header : "", question, answer }];
  });
}

function toRecord(result: unknown): Record<string, unknown> | null {
  let value = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * What the agent asked and what the person answered, read as a short exchange
 * rather than the JSON the call carried - the question card is gone once it is
 * answered, and this is where the choice stays visible.
 */
export function AskedResult({ asked }: { asked: AskedQuestion[] }) {
  const t = useTranslations("chat.tools");
  return (
    <ol className="space-y-3 py-1">
      {asked.map((item, index) => (
        <li key={`${item.header}-${index}`} className="space-y-1.5">
          {item.header !== "" && (
            <p className="text-muted-foreground font-mono text-[11px] tracking-[0.08em] uppercase">
              {item.header}
            </p>
          )}
          <p className="text-foreground text-[13px] font-medium">{item.question}</p>
          {item.answer === null ? (
            <p className="text-muted-foreground text-[13px]">{t("notAnsweredYet")}</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {item.answer.map((label) => (
                <span
                  key={label}
                  className="bg-muted text-foreground rounded-md px-2 py-0.5 text-[13px] font-medium"
                >
                  {label}
                </span>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
