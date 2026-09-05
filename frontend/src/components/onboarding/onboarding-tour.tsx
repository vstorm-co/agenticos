"use client";

import "driver.js/dist/driver.css";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import type { AllowedButtons, DriveStep, Driver } from "driver.js";

import { FETCHED_DETAIL_PAGES, useDetailTargets } from "@/components/onboarding/detail-targets";
import {
  activateTab,
  createTourDriver,
  isTypingTarget,
  pulse,
  revealDisclosures,
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
 * How long an `optional` stop waits for its target before skipping. Far below the
 * 4s a required target gets, because an optional target that is going to mount is
 * there as soon as its page is: the long wait only bought a hung-looking pause on
 * an empty catalog, where three optional MCP stops in a row sat 4s each while the
 * pinned caption looked stuck.
 */
const OPTIONAL_WAIT_MS = 800;

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
  const needsDetail = useMemo(
    () => steps.some((s) => s.page !== undefined && FETCHED_DETAIL_PAGES.has(s.page)),
    [steps],
  );
  const detailTargets = useDetailTargets(isOpen && needsDetail);
  const driverRef = useRef<Driver | null>(null);
  // Whether a transition is in flight. driver.js greys its own Next and Back for
  // one (`LOCKED_BUTTONS`); the arrow keys below are not its buttons, so they read
  // this instead — without it a held arrow would step past the control being
  // revealed and desync the walk from the page it is meant to be on.
  const lockedRef = useRef(false);

  const closeWalk = useCallback(() => {
    dismiss();
    if (mode === "tour") {
      toast.info(t("helpReminder"));
      router.push(ROUTES.DASHBOARD);
    }
  }, [dismiss, mode, router, t]);

  const completeWalk = useCallback(() => {
    closeWalk();
    if (mode === "tour") {
      openOffer("create-agent");
    } else if (mode === "page") {
      const flow = flowForPage(pageKey(stripLocale(pathname)));
      if (flow) openOffer(flow);
    }
  }, [closeWalk, mode, openOffer, pathname]);

  // The arrows walk the tour, which is what a reader who has already read the
  // caption reaches for rather than moving a mouse to a pinned button. Capture
  // phase, and only where the page is not taking the key for itself
  // (`isTypingTarget`). Left on the first step is deliberately nothing rather than
  // a close: the tour is a sequence, and backing out of one is what the X is for.
  useEffect(() => {
    if (!isOpen || !step || mode === "flow") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      if (lockedRef.current || isTypingTarget(event.target)) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") {
        if (!isFirst) back();
        return;
      }
      if (isLast) completeWalk();
      else next();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [isOpen, step, mode, isFirst, isLast, back, next, completeWalk]);

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

    const buttons: AllowedButtons[] = isFirst ? ["next", "close"] : ["previous", "next", "close"];
    const show = (element: Element | undefined, locked = false) => {
      lockedRef.current = locked;
      const driveStep: DriveStep = {
        element,
        popover: {
          // Pinned to the top on chat, where the composer the step points at is
          // itself at the bottom — a bottom-pinned caption sits over the prompt
          // box (#624). Everywhere else the default bottom pin holds.
          popoverClass: step.page === ROUTES.CHAT ? "tour-popover tour-popover-top" : undefined,
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
        // An optional step's tab can itself be conditional (the Memory tab renders only
        // when the capability is bound), so the activate wait takes the short timeout too.
        const trigger = await waitForElement(
          `[data-tour="${step.activate}"]`,
          signal,
          step.optional ? OPTIONAL_WAIT_MS : undefined,
        );
        if (signal.aborted) return;
        if (trigger instanceof HTMLElement) {
          show(trigger, true);
          await pulse(trigger, signal, REVEAL_MS);
          if (signal.aborted) return;
          activateTab(trigger);
        }
      }
      const element = step.target
        ? await waitForElement(
            `[data-tour="${step.target}"]`,
            signal,
            step.optional ? OPTIONAL_WAIT_MS : undefined,
          )
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
      // A `<details>` keeps its content in the document while hiding it, so the
      // wait above returns a control the reader cannot see and driver.js
      // spotlights a zero-height box.
      if (element) revealDisclosures(element);
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
    mode,
    t,
    detailTargets,
    closeWalk,
    completeWalk,
  ]);

  useEffect(() => () => driverRef.current?.destroy(), []);

  return null;
}
