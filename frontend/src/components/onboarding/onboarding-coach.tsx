"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { activateTab, waitForElement } from "@/components/onboarding/spotlight";
import { Button, IconButton } from "@/components/ui";
import { useOnboardingFlow } from "@/hooks/use-onboarding-flow";
import { stripLocale } from "@/lib/active-route";

/**
 * The target's box, in viewport coordinates, for the highlight ring, tagged with
 * the step it was measured for. The tag is what lets a step change clear the ring
 * without a reset call: a rect from the previous step simply stops matching and
 * stops rendering until the new target is found.
 */
interface Rect {
  stepId: string;
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * The interactive coach: it walks the reader through actually creating
 * something, the Phase-2 counterpart to the passive `OnboardingTour`.
 *
 * It deliberately draws no blocking overlay. driver.js's overlay sits above the
 * whole page and swallows clicks outside its spotlight, so a create dialog would
 * open behind it, dimmed and unusable — which is why a flow is a separate
 * mechanism rather than a driver mode. Here the only chrome is a ring around the
 * control (drawn with `pointer-events: none`, so it never intercepts a click) and
 * an instruction card pinned to the bottom. The real control, and the real
 * dialog it opens, are the reader's to operate.
 *
 * Advancement is the app's, not a button's: an interactive step ends when its
 * resource appears (`signalMet` from `useOnboardingFlow`), so the reader is never
 * told "now click Next" after doing the thing the step asked for. A step with no
 * signal (a "read this" stop) carries a Next; an optional one carries a Skip; and
 * the close button always ends the flow, because a walkthrough is never worth
 * trapping someone in. Mounted only while a flow runs, so the resource-count
 * queries its hook fires live only then.
 */
export function OnboardingCoach() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isActive, step, index, steps, isLast, signalMet, next, finish } = useOnboardingFlow();
  const [rect, setRect] = useState<Rect | null>(null);

  const stepId = step?.id;

  // Get to the page, reveal the tab that holds the control, find it, ring it.
  // The ring follows scroll and resize until the step changes or the flow ends.
  useEffect(() => {
    if (!isActive || !step) return;
    const controller = new AbortController();
    const { signal } = controller;
    const here = stripLocale(pathname);
    const sid = step.id;

    void (async () => {
      if (step.page && here !== step.page) {
        router.push(step.page);
        return; // this effect re-runs once the navigation lands
      }
      if (step.activate) {
        const trigger = await waitForElement(`[data-tour="${step.activate}"]`, signal);
        if (signal.aborted) return;
        if (trigger instanceof HTMLElement) activateTab(trigger);
      }
      if (!step.target) return;
      const target = await waitForElement(`[data-tour="${step.target}"]`, signal);
      if (signal.aborted || !(target instanceof HTMLElement)) return;
      const place = () => {
        const box = target.getBoundingClientRect();
        setRect({
          stepId: sid,
          top: box.top,
          left: box.left,
          width: box.width,
          height: box.height,
        });
      };
      place();
      window.addEventListener("scroll", place, true);
      window.addEventListener("resize", place);
      signal.addEventListener("abort", () => {
        window.removeEventListener("scroll", place, true);
        window.removeEventListener("resize", place);
      });
    })();

    return () => controller.abort();
  }, [isActive, step, stepId, pathname, router]);

  // The resource appeared — the reader did the thing. Advance, or end the flow if
  // this was the last step.
  useEffect(() => {
    if (isActive && signalMet) next();
  }, [isActive, signalMet, next]);

  if (!isActive || !step) return null;

  return (
    <>
      {rect && rect.stepId === stepId && (
        <div
          aria-hidden
          className="ring-primary pointer-events-none fixed z-[1000000000] rounded-lg ring-2 ring-offset-2 transition-all"
          style={{
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
          }}
        />
      )}
      <div
        role="dialog"
        aria-label={t(`steps.${step.id}.title`)}
        className="bg-popover text-popover-foreground fixed bottom-6 left-1/2 z-[1000000000] w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border p-4 shadow-lg"
      >
        <IconButton
          aria-label={t("coachClose")}
          onClick={finish}
          className="absolute top-2 right-2"
        >
          <X className="h-4 w-4" />
        </IconButton>
        <h2 className="pr-6 text-sm font-semibold">{t(`steps.${step.id}.title`)}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t(`steps.${step.id}.body`)}</p>
        <div className="mt-3 flex items-center justify-between gap-2">
          {steps.length > 1 ? (
            <span className="text-muted-foreground text-xs">
              {t("progress", { current: index + 1, total: steps.length })}
            </span>
          ) : (
            <span />
          )}
          {step.signal ? (
            step.optional && (
              <Button size="sm" variant="ghost" onClick={next}>
                {t("skip")}
              </Button>
            )
          ) : (
            <Button size="sm" onClick={next}>
              {isLast ? t("finish") : t("next")}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
