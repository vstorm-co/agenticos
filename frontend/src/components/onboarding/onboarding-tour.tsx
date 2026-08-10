"use client";

import "driver.js/dist/driver.css";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { AllowedButtons, DriveStep, Driver } from "driver.js";

import { createTourDriver, waitForElement } from "@/components/onboarding/spotlight";
import { useOnboardingTour } from "@/hooks";
import { stripLocale } from "@/lib/active-route";

/**
 * The guided tour: driver.js walks the reader across the product a page at a
 * time, spotlighting the useful controls on each with a caption anchored to
 * them.
 *
 * Not a modal, and not a hand-rolled panel either — the popover, its Next/Back,
 * its progress and the dimmed cut-out are all driver.js, which is why clicking
 * Next works where a custom panel's did not (driver.js swallows clicks outside
 * its own popover). This component owns only what driver.js cannot: it drives the
 * steps one at a time rather than as one array, because they span pages and
 * driver runs within a page — so Next on a page's last step navigates to the next
 * page and re-anchors there, and Back does the reverse. Which steps to show, in
 * what order, permission-filtered, and whether closing persists completion, all
 * come from `useOnboardingTour`. Mounted once in the dashboard layout: it
 * auto-opens on `/dashboard` for a user who has not finished onboarding, and the
 * header "?" replays a single page's highlights.
 */
export function OnboardingTour() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isOpen, steps, step, index, isFirst, isLast, next, back, dismiss } = useOnboardingTour();
  const driverRef = useRef<Driver | null>(null);

  useEffect(() => {
    driverRef.current ??= createTourDriver();
    const tour = driverRef.current;

    if (!isOpen || !step) {
      tour.destroy();
      return;
    }
    // Off the step's page: tear the overlay down so no popover is left pointing
    // at an element that is about to unmount, navigate, and let the resulting
    // pathname change re-run this effect on the destination.
    if (step.page && stripLocale(pathname) !== step.page) {
      tour.destroy();
      router.push(step.page);
      return;
    }

    const buttons: AllowedButtons[] = isFirst ? ["next", "close"] : ["previous", "next", "close"];
    const show = (element: Element | undefined) => {
      const driveStep: DriveStep = {
        element,
        popover: {
          title: t(`steps.${step.id}.title`),
          description: t(`steps.${step.id}.body`),
          showButtons: buttons,
          showProgress: true,
          progressText: t("progress", { current: index + 1, total: steps.length }),
          nextBtnText: isLast ? t("finish") : t("next"),
          prevBtnText: t("back"),
          onNextClick: () => (isLast ? dismiss() : next()),
          onPrevClick: () => back(),
          onCloseClick: () => dismiss(),
        },
      };
      tour.highlight(driveStep);
    };

    if (!step.target) {
      show(undefined);
      return;
    }
    const controller = new AbortController();
    void waitForElement(`[data-tour="${step.target}"]`, controller.signal).then((element) => {
      if (!controller.signal.aborted) show(element ?? undefined);
    });
    return () => controller.abort();
  }, [
    isOpen,
    step,
    index,
    steps.length,
    isFirst,
    isLast,
    pathname,
    router,
    next,
    back,
    dismiss,
    t,
  ]);

  useEffect(() => () => driverRef.current?.destroy(), []);

  return null;
}
