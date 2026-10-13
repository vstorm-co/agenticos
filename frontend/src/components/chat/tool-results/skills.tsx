"use client";
import { useTranslations } from "next-intl";

/** "market_data" -> "Market Data", "fire" -> "Fire". */
// One implementation, in `lib/tool-steps.ts`, because the step label above a
// `load_capability` call and the heading inside its result are the same words - and two
// title-casers drift the first time one of them learns about an acronym.
export { titleWords as formatSkillName } from "@/lib/tool-steps";

/**
 * The instructions a `load_capability` call brought back, or null if it brought none.
 *
 * Pydantic AI answers with `{"instructions": "# Skill: refunds\n\n…"}`. The heading is
 * the framework's own, and it repeats the skill name the step above already says, so it
 * is dropped - what a person opens this step for is the body underneath.
 *
 * Reached as an object where the socket kept the shape and as its JSON where something
 * stringified it on the way, so both are read. Anything else - an error sentence, a
 * capability that carried no instructions - is not a loaded skill, and the step says so
 * rather than drawing an empty box.
 */
export function parseLoadedSkill(result: unknown): string | null {
  const value = typeof result === "string" ? tryParse(result) : result;
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const instructions = (value as Record<string, unknown>).instructions;
  if (typeof instructions !== "string") return null;
  const body = instructions.replace(/^#\s+Skill:.*(\r?\n)+/, "").trim();
  return body === "" ? null : body;
}

function tryParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** Clean card for a loaded skill - the instructions, not the transport around them. */
export function LoadedSkillResult({ result, status }: { result: unknown; status: string }) {
  const t = useTranslations("chat.tools");
  if (result === undefined || status !== "completed") {
    return (
      <p className="text-muted-foreground py-2 text-xs italic">
        {status === "error" ? t("failedToLoadSkill") : t("loading")}
      </p>
    );
  }
  const body = parseLoadedSkill(result);
  if (body === null) {
    // A completed call whose result is not a loaded skill: the framework answers
    // an unknown capability id with a retry notice, and the socket records that
    // as `completed` like any other result. Rendering nothing made a refusal
    // look like a success unless somebody opened the raw view (#1704 review).
    const text = typeof result === "string" ? result : JSON.stringify(result);
    return (
      <p className="text-muted-foreground max-h-72 scrollbar-thin overflow-y-auto py-2 text-xs whitespace-pre-wrap">
        {text.trim() === "" ? t("failedToLoadSkill") : text}
      </p>
    );
  }

  return (
    <p className="text-foreground/75 max-h-72 scrollbar-thin overflow-y-auto py-1 text-[13px] leading-relaxed whitespace-pre-wrap">
      {body}
    </p>
  );
}

/**
 * The XML a `load_skill` call brought back, for a conversation recorded before
 * skills became deferred capabilities.
 *
 * Kept although nothing emits it any more: a stored transcript holds the tool
 * name and the result it actually got, so reopening an old thread without this
 * showed the library's raw `<skill>…</skill>` instead of the description it had
 * shown the day it ran (#1704 review).
 */
export function parseLoadSkillResult(result: string): { description: string } | null {
  const m = result.match(/<description>([\s\S]*?)<\/description>/);
  if (!m?.[1]) return null;
  return { description: m[1].trim() };
}

/** A loaded skill as a conversation from before the change recorded it. */
export function LoadSkillResult({ resultText, status }: { resultText: string; status: string }) {
  const t = useTranslations("chat.tools");
  if (!resultText || status !== "completed") {
    return (
      <p className="text-muted-foreground py-2 text-xs italic">
        {status === "error" ? t("failedToLoadSkill") : t("loading")}
      </p>
    );
  }
  const parsed = parseLoadSkillResult(resultText);
  if (!parsed) return null;

  return (
    <p className="text-foreground/75 py-1 text-[13px] leading-relaxed">{parsed.description}</p>
  );
}
