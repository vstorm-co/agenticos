import type { OptionColor } from "@/types/tables";

const NEUTRAL = "bg-muted/45 text-muted-foreground ring-border/60";

/** Dataset categories use neutral labels; red remains reserved for an actual refusal. */
export const DATASET_TONES: Record<OptionColor, string> = {
  gray: NEUTRAL,
  blue: NEUTRAL,
  green: NEUTRAL,
  yellow: NEUTRAL,
  purple: NEUTRAL,
  red: "bg-destructive/10 text-destructive-ink ring-destructive/20",
};
