import type { OptionColor } from "@/types/tables";

/** Stronger accents for dataset steps, controls and option chips. */
export const DATASET_TONES: Record<OptionColor, string> = {
  gray: "bg-muted text-muted-foreground ring-border",
  blue: "bg-dataset-blue text-dataset-blue-foreground ring-dataset-blue-foreground/20",
  green: "bg-dataset-green text-dataset-green-foreground ring-dataset-green-foreground/20",
  yellow: "bg-dataset-yellow text-dataset-yellow-foreground ring-dataset-yellow-foreground/20",
  purple: "bg-dataset-purple text-dataset-purple-foreground ring-dataset-purple-foreground/20",
  red: "bg-dataset-red text-dataset-red-foreground ring-dataset-red-foreground/20",
};
