"use client";

import { useTranslations } from "next-intl";

import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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
  ...props
}: Omit<ButtonProps, "onClick" | "disabled">) {
  const t = useTranslations("evals");
  const reason = t("needsRunsView");
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
