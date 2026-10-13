/** A translator that knows the `chat.steps` elapsed keys. */
type Translate = (
  key: "elapsedSeconds" | "elapsedMinutes",
  values: Record<string, number>,
) => string;

/**
 * How long something took, the way a person says it: "12s", "2m 39s".
 *
 * Whole seconds and never zero - a turn that answered in 300 ms still took a moment,
 * and "0s" reads as nothing having happened. The words come from the caller's
 * catalog, because "2 min 39 s" is how Polish writes the same thing.
 */
export function formatElapsed(ms: number, t: Translate): string {
  const total = Math.max(1, Math.round(ms / 1000));
  if (total < 60) return t("elapsedSeconds", { seconds: total });
  return t("elapsedMinutes", { minutes: Math.floor(total / 60), seconds: total % 60 });
}
