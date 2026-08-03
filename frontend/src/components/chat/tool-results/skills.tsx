"use client";

/** "market_data" -> "Market Data", "fire" -> "Fire". */
// One implementation, in `lib/tool-steps.ts`, because the step label above a
// `load_skill` call and the heading inside its result are the same words - and two
// title-casers drift the first time one of them learns about an acronym.
export { titleWords as formatSkillName } from "@/lib/tool-steps";

/** Extract the description text from a `load_skill` XML result.
 *  The library returns <skill><name>…</name><description>…</description>…</skill>. */
export function parseLoadSkillResult(result: string): { description: string } | null {
  const m = result.match(/<description>([\s\S]*?)<\/description>/);
  if (!m?.[1]) return null;
  return { description: m[1].trim() };
}

/** Clean card for a loaded skill - just the description, no raw XML. */
export function LoadSkillResult({ resultText, status }: { resultText: string; status: string }) {
  if (!resultText || status !== "completed") {
    return (
      <p className="text-muted-foreground py-2 text-xs italic">
        {status === "error" ? "Failed to load skill." : "Loading…"}
      </p>
    );
  }
  const parsed = parseLoadSkillResult(resultText);
  if (!parsed) return null;

  return (
    <p className="text-foreground/75 py-1 text-[13px] leading-relaxed">{parsed.description}</p>
  );
}
