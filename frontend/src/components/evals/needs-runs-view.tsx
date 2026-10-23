"use client";

import { useTranslations } from "next-intl";

import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { RunNeed } from "@/types/datasets";

/** Which sentence says what is missing, by what is. */
function reasonKey(needs: RunNeed[]) {
  if (!needs.includes("datasets:run")) return "needsRunsView" as const;
  return needs.includes("runs:view")
    ? ("needsRunsViewAndDatasetRun" as const)
    : ("needsDatasetRun" as const);
}

/**
 * A start control the caller may not use for want of `runs:view`, shown disabled
 * and saying why. Starting an eval needs it: a run is paid for, and whoever
 * cannot read it or cancel it should not start one.
 *
 * `aria-disabled` rather than `disabled`, because a disabled button takes no
 * focus and, in some browsers, no hover - so its reason would never be read.
 */
export function NeedsRunsView({
  children,
  className,
  needs = ["runs:view"],
  ...props
}: Omit<ButtonProps, "onClick" | "disabled"> & {
  /** What the caller lacks: reading runs, running this dataset, or both. */
  needs?: RunNeed[];
}) {
  const t = useTranslations("evals");
  const reason = t(reasonKey(needs));
  return (
    <Button
      {...props}
      aria-disabled="true"
      title={reason}
      className={cn("cursor-not-allowed opacity-50", className)}
      onClick={(event) => event.preventDefault()}
    >
      {children}
      <span className="sr-only">{reason}</span>
    </Button>
  );
}
