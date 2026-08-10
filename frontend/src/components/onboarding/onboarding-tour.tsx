"use client";

import "driver.js/dist/driver.css";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { createSpotlight, waitForElement } from "@/components/onboarding/spotlight";
import { Button } from "@/components/ui";
import { useOnboardingTour } from "@/hooks";
import { stripLocale } from "@/lib/active-route";

/**
 * The guided tour: a panel docked to the foot of the window that walks the
 * reader across the product a page at a time, spotlighting one useful control on
 * each.
 *
 * Not a modal. Next takes the reader to the step's page and dims everything but
 * the control the copy is about, so the tour teaches the real screen rather than
 * describing it in a box over a greyed-out one. driver.js draws the overlay and
 * the cut-out (`spotlight.ts`); this component owns the copy, the buttons and the
 * page-to-page navigation, and reads which steps to show — permission-filtered —
 * from `useOnboardingTour`. Mounted once in the dashboard layout: it auto-opens
 * on `/dashboard` for a user who has not finished onboarding, and the help button
 * in the page header replays it.
 */
export function OnboardingTour() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isOpen, steps, step, index, isFirst, isLast, next, back, dismiss } = useOnboardingTour();
  const spotlightRef = useRef<ReturnType<typeof createSpotlight> | null>(null);

  useEffect(() => {
    spotlightRef.current ??= createSpotlight();
    const spotlight = spotlightRef.current;

    if (!isOpen || !step) {
      spotlight.destroy();
      return;
    }
    // Off the step's page: navigate, and let the resulting pathname change re-run
    // this effect on the destination, where the target has a chance to exist.
    if (step.page && stripLocale(pathname) !== step.page) {
      router.push(step.page);
      return;
    }
    if (!step.target) {
      spotlight.destroy();
      return;
    }
    const controller = new AbortController();
    void waitForElement(`[data-tour="${step.target}"]`, controller.signal).then((element) => {
      if (element) spotlight.show(element);
      else spotlight.destroy();
    });
    return () => controller.abort();
  }, [isOpen, step, pathname, router]);

  useEffect(() => () => spotlightRef.current?.destroy(), []);

  if (!isOpen || !step) return null;

  return (
    <div
      role="region"
      aria-labelledby="onboarding-tour-title"
      className="fixed inset-x-0 bottom-0 z-[10001] flex justify-center px-4 pb-4"
    >
      <div className="bg-card w-full max-w-2xl rounded-xl border p-5 shadow-2xl">
        <p className="text-muted-foreground mb-1 text-xs font-medium" aria-live="polite">
          {t("progress", { current: index + 1, total: steps.length })}
        </p>
        <h2 id="onboarding-tour-title" className="text-base font-semibold">
          {t(`steps.${step.id}.title`)}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          {t(`steps.${step.id}.body`)}
        </p>

        <div className="mt-4 flex items-center justify-between gap-2">
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
        </div>
      </div>
    </div>
  );
}
