"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useOnboardingTour } from "@/hooks";
import { cn } from "@/lib/utils";

/**
 * The first-run walkthrough: a sequence of steps in a modal, not a spotlight
 * anchored to page elements.
 *
 * The modal is the whole design. It rides the shared Radix Dialog, which brings
 * the focus trap, Escape-to-close and keyboard handling a tour needs — so the
 * feature ships no new dependency, and its content is one message per step
 * rather than fifteen tooltips glued to controls that move. Mounted once in the
 * dashboard layout: `useOnboardingTour` opens it on `/dashboard` for a user who
 * has not finished onboarding, and the restart control in the page header
 * reopens it. Which steps it shows is filtered by permission there, so a
 * dismissal from any step persists and a Viewer never lands on a page they
 * cannot reach.
 */
export function OnboardingTour() {
  const t = useTranslations("onboarding");
  const { isOpen, steps, index, isFirst, isLast, next, back, dismiss } = useOnboardingTour();

  const step = steps[index];
  if (!step) return null;
  const Icon = step.icon;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && dismiss()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <span
            aria-hidden
            className="bg-accent text-foreground mb-2 inline-flex h-11 w-11 items-center justify-center rounded-xl"
          >
            <Icon className="h-5 w-5" />
          </span>
          <DialogTitle>{t(`steps.${step.id}.title`)}</DialogTitle>
          <DialogDescription className="leading-relaxed">
            {t(`steps.${step.id}.body`)}
          </DialogDescription>
        </DialogHeader>

        <p className="sr-only" aria-live="polite">
          {t("progress", { current: index + 1, total: steps.length })}
        </p>
        <div aria-hidden className="flex items-center justify-center gap-1.5 py-1">
          {steps.map((s, i) => (
            <span
              key={s.id}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === index ? "bg-foreground w-4" : "bg-muted w-1.5",
              )}
            />
          ))}
        </div>

        <DialogFooter className="sm:items-center sm:justify-between">
          <Button variant="ghost" size="sm" onClick={dismiss}>
            {t("skip")}
          </Button>
          <div className="flex items-center gap-2">
            {!isFirst && (
              <Button variant="outline" size="sm" onClick={back}>
                {t("back")}
              </Button>
            )}
            <Button size="sm" onClick={isLast ? dismiss : next}>
              {isLast ? t("finish") : t("next")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
