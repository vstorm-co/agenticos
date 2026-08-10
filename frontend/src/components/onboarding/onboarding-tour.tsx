"use client";

import "driver.js/dist/driver.css";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { AllowedButtons, DriveStep, Driver } from "driver.js";

import { useDetailTargets } from "@/components/onboarding/detail-targets";
import { activateTab, createTourDriver, waitForElement } from "@/components/onboarding/spotlight";
import { useOnboardingTour } from "@/hooks";
import { stripLocale } from "@/lib/active-route";
import { pageKey } from "@/lib/onboarding/tour";

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
 * driver runs within a page.
 *
 * Three moves get the reader to a step. A static step navigates to its route.
 * A *detail* step (the agent builder, a collection, an organization — routes
 * that are per-row) resolves an example to open through `useDetailTargets`,
 * navigates into it, and — once there — leaves the reader on whichever row they
 * are already looking at; if there is nothing to open (an empty list), it
 * describes the section centered rather than skip it, so the "?" still explains
 * what a detail view holds before there is any data to open one on. And a step
 * with an `activate` target switches to that Radix tab, then spotlights the
 * target its panel holds — one Next, one panel, and the popover stays put on it
 * to be read rather than sliding off mid-sentence. Which steps to show, in what
 * order, permission-filtered, and whether closing persists completion, all come
 * from `useOnboardingTour`. Mounted once in the dashboard layout.
 */
export function OnboardingTour() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isOpen, steps, step, index, isFirst, isLast, next, back, dismiss } = useOnboardingTour();
  const detailTargets = useDetailTargets(isOpen);
  const driverRef = useRef<Driver | null>(null);

  useEffect(() => {
    driverRef.current ??= createTourDriver();
    const tour = driverRef.current;

    if (!isOpen || !step) {
      tour.destroy();
      return;
    }

    const here = stripLocale(pathname);
    const detail = step.page ? detailTargets[step.page] : undefined;

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

    if (detail) {
      // A detail pseudo-page. If we are not already on one of its routes, open an
      // example; once on such a route we stay on it (the "?" replayed from a
      // builder means *this* agent) and fall through to activate + highlight.
      if (pageKey(here) !== step.page) {
        if (detail.href) {
          tour.destroy();
          router.push(detail.href);
          return;
        }
        if (detail.pending) return; // wait for the list; this effect re-runs when it settles
        // Nothing to open — an empty list. Describe the section where we are
        // rather than skip it, so the walk still says what a detail view holds.
        show(undefined);
        return;
      }
    } else if (step.page && here !== step.page) {
      // A static step the tour is not on yet: tear the overlay down so no popover
      // is left pointing at an element that is about to unmount, navigate, and let
      // the resulting pathname change re-run this effect on the destination.
      tour.destroy();
      router.push(step.page);
      return;
    }

    if (!step.target && !step.activate) {
      show(undefined);
      return;
    }

    const controller = new AbortController();
    void (async () => {
      // A tab whose panel holds the target only mounts once its trigger is
      // activated, so switch to it first — then the one spotlight lands on the
      // target and stays there until Next, never sliding off it mid-read.
      if (step.activate) {
        const trigger = await waitForElement(`[data-tour="${step.activate}"]`, controller.signal);
        if (controller.signal.aborted) return;
        if (trigger instanceof HTMLElement) activateTab(trigger);
      }
      const element = step.target
        ? await waitForElement(`[data-tour="${step.target}"]`, controller.signal)
        : undefined;
      if (!controller.signal.aborted) show(element ?? undefined);
    })();
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
    detailTargets,
  ]);

  useEffect(() => () => driverRef.current?.destroy(), []);

  return null;
}
