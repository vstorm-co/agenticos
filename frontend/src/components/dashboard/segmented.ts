import { cn } from "@/lib/utils";

import { CHOICE_SURFACE, CHOICE_OPTION } from "@/components/ui/control-styles";

/** Visual choice family shared with settings; these callers retain action semantics. */
export const SEGMENTED_CLASS = cn(
  CHOICE_SURFACE,
  "flex w-fit shrink-0 scrollbar-none max-md:overflow-x-auto [&>*]:shrink-0 [&>*]:whitespace-nowrap",
);

export function segment(active: boolean): string {
  return cn(
    CHOICE_OPTION,
    active
      ? "bg-control-active text-foreground font-semibold"
      : "text-muted-foreground hover:text-foreground",
  );
}
