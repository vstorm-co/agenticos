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
  pending = false,
  bodyKey,
}: {
  title: string;
  description: string;
  progress?: { steps: WizardStep[]; current: string };
  children: ReactNode;
  footer?: ReactNode;
  disabled?: boolean;
  /** A request blocks dismissal; a prepared local-consent draft only disables fields. */
  pending?: boolean;
  bodyKey?: string;
}) {
  return (
    <DialogContent
      dismissible={!pending}
      className={cn(DIALOG_FRAMED, DIALOG_FORM, "gap-0 sm:gap-0 sm:p-0")}
      style={{ backgroundColor: "var(--color-card)" }}
    >
      <DialogHeader className="border-foreground/10 border-b px-4 pt-4 pb-3 sm:px-6">
        <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        {progress && <WizardSteps steps={progress.steps} current={progress.current} responsive />}
      </DialogHeader>
      <fieldset
        key={bodyKey}
        disabled={disabled}
        className="wizard-step-in min-h-0 min-w-0 scrollbar-thin overflow-y-auto px-4 py-4 sm:px-6"
      >
        <legend className="sr-only">{title}</legend>
        {children}
      </fieldset>
      {footer}
    </DialogContent>
  );
}
