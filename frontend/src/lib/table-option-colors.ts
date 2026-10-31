import type { OptionColor } from "@/types/tables";

export const OPTION_TONES: Record<OptionColor, string> = {
  gray: "bg-muted text-foreground",
  blue: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  green: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  yellow: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  purple: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
  red: "bg-rose-500/10 text-rose-700 dark:text-rose-300",
};
