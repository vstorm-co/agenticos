"use client";

import type { ReactElement } from "react";
import { Check, FlaskConical, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { ActionTooltip } from "@/components/ui/action-tooltip";
import { TooltipProvider } from "@/components/ui/tooltip";

type ProbeStatus = "idle" | "testing" | "passed" | "failed";

/**
 * The Test that unlocks a save. Filled while a test is still owed, so it reads as
 * the next step; outlined with a check once these exact values passed.
 */
export function ProbeTestButton({
  status,
  disabled,
  onClick,
}: {
  status: ProbeStatus;
  disabled: boolean;
  onClick: () => void;
}) {
  const t = useTranslations("kb");
  const passed = status === "passed";
  return (
    <Button
      type="button"
      variant={passed ? "outline" : "default"}
      disabled={disabled || status === "testing"}
      onClick={onClick}
    >
      {status === "testing" ? (
        <Loader2 className="size-4 animate-spin" aria-hidden />
      ) : passed ? (
        <Check className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />
      ) : (
        <FlaskConical className="size-4" aria-hidden />
      )}
      {status === "testing" ? t("testingSettings") : passed ? t("tested") : t("testSettings")}
    </Button>
  );
}

/** A disabled button that says why on hover; an enabled one is left alone. */
export function WhyDisabled({
  reason,
  children,
}: {
  reason: string | null;
  children: ReactElement;
}) {
  if (reason === null) return children;
  // Its own provider, so a dialog rendered outside the app shell still gets one.
  return (
    <TooltipProvider>
      <ActionTooltip label={reason} disabled>
        {children}
      </ActionTooltip>
    </TooltipProvider>
  );
}
