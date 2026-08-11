"use client";

import "driver.js/dist/driver.css";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import type { AllowedButtons, DriveStep, Driver } from "driver.js";

import { useDetailTargets } from "@/components/onboarding/detail-targets";
import {
  activateTab,
  createTourDriver,
  pulse,
  waitForElement,
} from "@/components/onboarding/spotlight";
import { useOnboardingTour } from "@/hooks";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { flowForPage } from "@/lib/onboarding/flows";
import { pageKey } from "@/lib/onboarding/tour";
import { useOnboardingStore } from "@/stores";

/** How long the control that drives a transition is spotlighted before it fires. */
const REVEAL_MS = 650;

/** How long to wait for that control to be in the DOM before giving up on the flourish. */
const CONTROL_WAIT_MS = 400;

/**
 * The buttons greyed out while a transition is in flight. Next and Back are
 * locked so a reader cannot advance past the control being revealed and desync
 * the walk from the page; close stays live so they can always leave.
 */
const LOCKED_BUTTONS: AllowedButtons[] = ["next", "previous"];

/**
 * The guided tour: driver.js walks the reader across the product a page at a
 * time, spotlighting the useful controls on each with a caption.
 *
 * The caption and its Next/Back/close are driver.js's own popover, but pinned to
 * a fixed spot at the bottom of the screen (`popoverClass` + `globals.css`), so
 * the text and the Next button hold still for the whole walk and only the
 * spotlight cut-out moves. That is what makes a transition legible rather than
 * disorienting: the reader is never chasing the words around the screen.
 *
 * Every move to the next step is driven by Next, and every move shows what
 * causes it. A static or detail step that needs another page first spotlights
 * the control that leads there — the sidebar link, or the button that opens the
 * row (the "Roles" link, an agent's card) — pulses it like a press, then
 * navigates; a step with an `activate` target pulses its Radix tab, then
 * switches to it. Only then does the spotlight land on the step's target.
 * Because the caption is pinned, none of that moves the text: the pulse is for
 * the eye to follow the highlight, not a timer the reader races. While a
 * transition is in flight Next and Back are greyed (`LOCKED_BUTTONS`), so a
 * reader cannot click past the control being revealed and desync the walk from
 * the page it is meant to be on; they re-enable once the destination is shown.
 * A detail step with nothing to open (an empty list) describes the section where
 * the reader is rather than skip it. Which steps to show, in what order,
 * permission-filtered, and whether closing persists completion, all come from
 * `useOnboardingTour`. Ending the first-run tour returns the reader to the
 * dashboard rather than leaving them on its last page; the "?" replay leaves
 * them where they opened it. A "?" walk that runs to its end offers the
 * interactive flow that creates the section's resource (`flowForPage` →
 * `CreationOffer`); an early close does not. While a flow runs the passive
 * overlay stays down so the coach can own the screen. Mounted once in the
 * dashboard layout.
 */
export function OnboardingTour() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isOpen, steps, step, index, isFirst, isLast, next, back, dismiss } = useOnboardingTour();
  const mode = useOnboardingStore((state) => state.mode);
  const openOffer = useOnboardingStore((state) => state.openOffer);
  const detailTargets = useDetailTargets(isOpen);
  const driverRef = useRef<Driver | null>(null);

  useEffect(() => {
    driverRef.current ??= createTourDriver();
    const tour = driverRef.current;

    // While an interactive flow runs, the coach owns the screen — the passive
    // driver.js overlay must stay down so it does not sit over the create dialog.
    if (!isOpen || !step || mode === "flow") {
      tour.destroy();
      return;
    }

    const here = stripLocale(pathname);
    const detail = step.page ? detailTargets[step.page] : undefined;

    // Close the walk, then land on the dashboard — but only the first-run tour,
    // which walks the whole product and would otherwise strand a new user on its
    // last page (mcp-servers) rather than the home they started on. A "?" replay
    // is help on one page, so closing it leaves the reader exactly where it was
    // opened. This is the early exit — the X, or Escape — and it makes no offer.
    // Either way out of the first run — skipped here or finished through
    // completeWalk below — leaves one reminder behind: the tour never returns
    // (completion is recorded server-side), so the toast is where the reader
    // learns the "?" replays any page's tips whenever they want them.
    const closeWalk = () => {
      dismiss();
      if (mode === "tour") {
        toast.info(t("helpReminder"));
        router.push(ROUTES.DASHBOARD);
      }
    };

    // Reaching the end — Next on the last step. Everything closeWalk does, and
    // then the offer: a "?" walk that ran to its end asks whether to create the
    // thing its section is for (the interactive Phase-2 flow). Only a completed
    // walk asks; someone who left early was not finishing, and a section with
    // nothing to create — or one whose create the caller may not perform — makes
    // no offer, because `flowForPage` returns null and `CreationOffer` re-checks
    // the permission.
    const completeWalk = () => {
      closeWalk();
      if (mode === "tour") {
        // The first-run tour finished — offer to build the first agent together.
        // Declining guides nobody; the reader can still start it later from the
        // Agents "?" walk, whose end offers the same flow.
        openOffer("create-agent");
      } else if (mode === "page") {
        const flow = flowForPage(pageKey(here));
        if (flow) openOffer(flow);
      }
    };

    const buttons: AllowedButtons[] = isFirst ? ["next", "close"] : ["previous", "next", "close"];
    const show = (element: Element | undefined, locked = false) => {
      const driveStep: DriveStep = {
        element,
        popover: {
          title: t(`steps.${step.id}.title`),
          description: t(`steps.${step.id}.body`),
          showButtons: buttons,
          disableButtons: locked ? LOCKED_BUTTONS : undefined,
          showProgress: true,
          progressText: t("progress", { current: index + 1, total: steps.length }),
          nextBtnText: isLast ? t("finish") : t("next"),
          prevBtnText: t("back"),
          onNextClick: () => (isLast ? completeWalk() : next()),
          onPrevClick: () => back(),
          onCloseClick: () => closeWalk(),
        },
      };
      tour.highlight(driveStep);
    };

    const controller = new AbortController();
    const { signal } = controller;

    // Spotlight the control that drives a transition and pulse it like a press,
    // so the reader sees which one before it fires. Next stays greyed for the
    // hold so the walk cannot be advanced mid-transition. A control that never
    // shows (a permission hid it, a slow page) just means the transition happens
    // without the flourish rather than stalling the walk.
    const reveal = async (selector: string) => {
      const control = await waitForElement(selector, signal, CONTROL_WAIT_MS);
      if (signal.aborted || !(control instanceof HTMLElement)) return;
      show(control, true);
      await pulse(control, signal, REVEAL_MS);
    };

    void (async () => {
      // Get to the right page first, showing the control that leads there. The
      // overlay is not torn down across the navigation, so the pinned caption
      // stays on screen the whole way rather than blinking out mid-move.
      if (detail) {
        if (pageKey(here) !== step.page) {
          if (detail.href) {
            await reveal(`a[href$="${detail.href}"]`);
            if (signal.aborted) return;
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
        await reveal(`a[href$="${step.page}"]`);
        if (signal.aborted) return;
        router.push(step.page);
        return;
      }

      // On the right page. Reveal the tab that opens the section, switch to it,
      // then land the spotlight on the target — the caption never having moved.
      if (step.activate) {
        const trigger = await waitForElement(`[data-tour="${step.activate}"]`, signal);
        if (signal.aborted) return;
        if (trigger instanceof HTMLElement) {
          show(trigger, true);
          await pulse(trigger, signal, REVEAL_MS);
          if (signal.aborted) return;
          activateTab(trigger);
        }
      }
      const element = step.target
        ? await waitForElement(`[data-tour="${step.target}"]`, signal)
        : undefined;
      if (signal.aborted) return;
      // An optional stop whose target never mounted — the MCP catalog's filter,
      // add and connect controls when the catalog is empty — is skipped rather
      // than pinned to the middle of the screen with nothing highlighted.
      if (step.optional && step.target && !element) {
        if (isLast) completeWalk();
        else next();
        return;
      }
      show(element ?? undefined);
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
    mode,
    openOffer,
    t,
    detailTargets,
  ]);

  useEffect(() => () => driverRef.current?.destroy(), []);

  return null;
}
