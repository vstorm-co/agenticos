/** A translator that knows the `chat.days` keys. */
type Translate = (key: "today" | "yesterday") => string;

function startOfDay(at: Date): number {
  return new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
}

/**
 * Whether the transcript marks a new day before message `index`, by the reader's
 * own calendar.
 *
 * At every change of day, and above the first message unless it is from today -
 * a thread wholly from today gains nothing from a pill saying so, while one
 * reopened a week later is worth placing in time before its first word.
 */
export function startsADay(timestamps: Date[], index: number, now: Date): boolean {
  const at = timestamps[index];
  if (at === undefined) return false;
  const previous = timestamps[index - 1];
  if (previous === undefined) return startOfDay(at) !== startOfDay(now);
  return startOfDay(at) !== startOfDay(previous);
}

/** "Today", "Yesterday", "Monday, 12 October" - with the year once it is not this one. */
export function dayLabel(at: Date, now: Date, locale: string, t: Translate): string {
  const days = Math.round((startOfDay(now) - startOfDay(at)) / 86_400_000);
  if (days === 0) return t("today");
  if (days === 1) return t("yesterday");
  return new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  }).format(at);
}
