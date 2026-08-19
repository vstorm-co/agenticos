import { CalendarClock, Code2, Globe, MessageSquare, Zap } from "lucide-react";

import { brandMark } from "@/components/icons/brand-icon";
import { cn } from "@/lib/utils";
import type { Translate } from "@/lib/agent-step-captions";

/**
 * One mark per `RunSurface` value - the single mapping the run table and the
 * surface filter both draw from, so a surface never wears two faces (#144's
 * rule, applied to surfaces).
 *
 * The messaging channels get their brand marks, the same components the
 * channels list draws, monochrome `currentColor` like every brand mark in the
 * console. The console's own surfaces speak the exposure cards' vocabulary
 * (`surface-picker.tsx`): a run from the widget wears the Website widget
 * card's globe, an API run the Public API card's code tag - so what somebody
 * published and what ran through it carry the same face. The dashboard chat,
 * which no card publishes, is the chat bubble.
 */
const MARKS = {
  web: MessageSquare,
  embed: Globe,
  api: Code2,
  slack: brandMark("slack"),
  telegram: brandMark("telegram"),
  mattermost: brandMark("mattermost"),
  // Nobody sat at a keyboard for these two: a clock for the run a schedule was
  // due to make, a bolt for the one an event fired. They are in this table and
  // not yet in `SURFACES` on the filter bar, because the filter's vocabulary is
  // what the backend will validate a query against - offering a value it refuses
  // is a 422, and the branch that writes these surfaces adds them there.
  schedule: CalendarClock,
  trigger: Zap,
} as const;

/** The display name beside the mark - "Mattermost", not the enum's lowercase. */
const LABEL_KEYS = {
  web: "surfaceWeb",
  embed: "surfaceEmbed",
  api: "surfaceApi",
  slack: "surfaceSlack",
  telegram: "surfaceTelegram",
  mattermost: "surfaceMattermost",
  schedule: "surfaceSchedule",
  trigger: "surfaceTrigger",
} as const;

/**
 * What a surface is called on screen, from the same module that draws its
 * mark - one vocabulary. A surface this build has no name for falls back to
 * the raw value, the same honesty the mark shows by rendering nothing.
 */
export function surfaceLabel(surface: string, t: Translate): string {
  const key = LABEL_KEYS[surface as keyof typeof LABEL_KEYS];
  return key === undefined ? surface : t(key);
}

/**
 * The mark alone, decorative beside its own name.
 *
 * Callers render the surface name next to it, which is what carries the fact
 * for a screen reader - so the icon is `aria-hidden`, never a second, redundant
 * announcement of the same word.
 */
export function SurfaceIcon({ surface, className }: { surface: string; className?: string }) {
  // The table directly rather than through the accessor below: a lookup that
  // goes via a function reads to the compiler's rules as a component *created*
  // during render, and the two are the same table either way.
  const Mark = MARKS[surface as keyof typeof MARKS];
  if (Mark === undefined) return null;
  return <Mark className={cn("h-3.5 w-3.5 shrink-0", className)} aria-hidden />;
}

/**
 * The mark itself, for a caller that needs the component rather than an element.
 *
 * The agent map's tiles take an icon as a prop, and reading `MARKS` there would
 * be a second table - which is the thing this module exists to prevent.
 */
export function surfaceIconComponent(surface: string) {
  return MARKS[surface as keyof typeof MARKS];
}
