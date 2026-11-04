import { cn } from "@/lib/utils";

/**
 * The dashboard's segmented control: one pill holding the choices, the chosen
 * one filled in ink. Shared by the view switcher and the period control so the
 * two rows read as one kind of control rather than two.
 *
 * Loose `text-xs` chips with a square-cornered fill read as smaller and
 * squarer than every button beside them, which is what this replaced. One line
 * that scrolls on a phone wherever it is placed: squeezed, its buttons broke
 * "Last 7 days" over three lines.
 */
export const SEGMENTED_CLASS =
  "border-border bg-muted/60 flex w-fit max-w-full shrink-0 scrollbar-none items-center gap-0.5 rounded-full border p-0.5 max-md:overflow-x-auto [&>*]:shrink-0 [&>*]:whitespace-nowrap";

/** One choice on the control: a pill, filled in ink when it is the one chosen. */
export function segment(active: boolean): string {
  return cn(
    "flex h-8 touch:min-h-11 touch-manipulation items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors",
    active
      ? "bg-primary text-primary-foreground shadow-card"
      : "text-muted-foreground hover:text-foreground",
  );
}
