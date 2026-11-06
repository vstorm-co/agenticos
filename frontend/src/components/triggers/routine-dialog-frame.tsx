"use client";

import type { ReactNode } from "react";

import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  WizardSteps,
  type WizardStep,
} from "@/components/ui";
import { DIALOG_FORM, DIALOG_FRAMED } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

/** One frame for scheduled, event-driven and monitoring routines. */
export function RoutineDialogFrame({
  title,
  description,
  progress,
  children,
  footer,
  disabled = false,
  bodyKey,
}: {
  title: string;
  description: string;
  progress?: { steps: WizardStep[]; current: string };
  children: ReactNode;
  footer?: ReactNode;
  disabled?: boolean;
  bodyKey?: string;
}) {
  return (
    <DialogContent
      className={cn(DIALOG_FRAMED, DIALOG_FORM, "gap-0 sm:gap-0 sm:p-0")}
      style={{ backgroundColor: "var(--color-card)" }}
    >
      <DialogHeader className="border-foreground/10 border-b px-6 pt-4 pb-3">
        <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        {progress && <WizardSteps steps={progress.steps} current={progress.current} />}
      </DialogHeader>
      <fieldset
        key={bodyKey}
        disabled={disabled}
        className="wizard-step-in min-h-0 min-w-0 scrollbar-thin overflow-y-auto px-6 py-4"
      >
        {children}
      </fieldset>
      {footer}
    </DialogContent>
  );
}
