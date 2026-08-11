"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { activateTab, spotlightPath, waitForElement } from "@/components/onboarding/spotlight";
import { Button, IconButton } from "@/components/ui";
import { useOnboardingFlow } from "@/hooks/use-onboarding-flow";
import { stripLocale } from "@/lib/active-route";

/** The class that outlines the spotlighted control; drawn and pulsed in `globals.css`. */
const HIGHLIGHT_CLASS = "onboarding-coach-target";

/** Space between the control and the freeze layer's cut-out, so the pulse plays inside it. */
const HOLE_PADDING = 10;
const HOLE_RADIUS = 12;

/** The dim the freeze layer paints over the frozen page. */
const DIM = "rgba(10, 10, 10, 0.5)";

/**
 * The target's box in viewport coordinates, tagged with the step it was measured
 * for. The tag is what lets a step change clear the cut-out without a reset call:
 * a rect from the previous step stops matching `stepId` and stops rendering until
 * the new target is found.
 */
interface Rect {
  stepId: string;
  top: number;
  left: number;
  width: number;
  height: number;
}

/** An open modal dialog, ours excepted — Radix marks its content `data-state`, the coach card does not. */
const OPEN_DIALOG = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]';

/**
 * The interactive coach: it walks the reader through actually creating
 * something, the Phase-2 counterpart to the passive `OnboardingTour`.
 *
 * Unlike the tour it does not hand control to driver.js. driver's overlay sits
 * above the whole page and swallows clicks outside its spotlight, so the create
 * dialog the reader has to fill would open behind it, dimmed and unusable. So the
 * coach draws its own freeze: a full-viewport dim with a cut-out over the one
 * control the step is about (`spotlightPath`), painted so clicks land only inside
 * the hole. That is what keeps a guided step guided — the reader cannot wander to
 * another tab or the sidebar mid-flow, only operate the control being pointed at.
 *
 * The freeze steps aside the moment a modal dialog opens (`OPEN_DIALOG`): a Radix
 * dialog is already modal and dims the page itself, so a second freeze over it
 * would only fight its stacking and re-dim it — exactly the trap that kept the
 * coach driver-less. While the dialog is up the reader fills it against Radix's
 * own overlay, and the step advances when its resource appears.
 *
 * The control itself is marked with `HIGHLIGHT_CLASS`, so the outline is on the
 * element and tracks it on scroll with no JS to lag behind — and it is scrolled
 * into view first, because the freeze eats wheel events and the reader cannot
 * bring it into view themselves.
 *
 * Advancement is the app's, not a button's: a step with a signal ends when its
 * resource appears (`signalMet` from `useOnboardingFlow`), so the reader is never
 * told "now click Next" after doing the thing the step asked for, and carries no
 * button — the doing is the advance. A step with no signal (write instructions,
 * or an optional "attach one or move on") carries a Next. The close button always
 * ends the flow, because a walkthrough is never worth trapping someone in.
 * Mounted only while a flow runs, so the resource-count queries its hook fires
 * live only then.
 */
export function OnboardingCoach() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const { isActive, step, index, steps, isLast, signalMet, next, finish } = useOnboardingFlow();
  const [rect, setRect] = useState<Rect | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const stepId = step?.id;

  // The freeze must yield to a modal dialog the moment one opens and take back
  // over when it closes — watched here rather than polled, so the handover is a
  // frame, not a tick.
  useEffect(() => {
    if (!isActive) return;
    const check = () => setDialogOpen(document.querySelector(OPEN_DIALOG) !== null);
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-state", "role"],
    });
    return () => observer.disconnect();
  }, [isActive]);

  // Get to the page, reveal the tab that holds the control, find it, scroll it
  // into view, and mark it. The outline rides the element on scroll; the cut-out
  // is repositioned on scroll and resize until the step changes or the flow ends.
  useEffect(() => {
    if (!isActive || !step) return;
    const controller = new AbortController();
    const { signal } = controller;
    const here = stripLocale(pathname);
    const sid = step.id;

    void (async () => {
      // Only real routes are navigable. A detail view's pseudo-identity (the
      // builder's `AGENT_BUILDER`) is reached by the step before it — creating the
      // agent opens the builder — so the coach never pushes one; it just proceeds
      // to find the target on the page it was left on.
      if (step.page?.startsWith("/") && here !== step.page) {
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

      target.scrollIntoView({ block: "center", inline: "center" });
      target.classList.add(HIGHLIGHT_CLASS);
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
        target.classList.remove(HIGHLIGHT_CLASS);
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

  const current = rect?.stepId === stepId ? rect : null;

  return (
    <>
      {!dialogOpen && <FreezeLayer rect={current} />}
      <div
        role="dialog"
        aria-label={t(`steps.${step.id}.title`)}
        className="bg-popover text-popover-foreground fixed bottom-6 left-1/2 z-[1000000001] w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border p-4 shadow-lg"
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
          {!step.signal && (
            <Button size="sm" onClick={next}>
              {isLast ? t("finish") : t("next")}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}

/**
 * The dim that freezes the page. With a located target it paints everything but a
 * cut-out over the control (`spotlightPath`), so only that control is clickable;
 * before one is found — navigating, or waiting for a control to mount — it paints
 * the whole viewport, so the reader cannot wander off mid-step. The SVG itself
 * takes no pointer events; only its painted fill does, so clicks in the hole fall
 * through to the real control while every other click is swallowed.
 */
function FreezeLayer({ rect }: { rect: Rect | null }) {
  if (typeof window === "undefined") return null;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!rect) {
    return (
      <div
        aria-hidden
        data-coach-freeze
        className="fixed inset-0 z-[1000000000]"
        style={{ background: DIM }}
      />
    );
  }
  const d = spotlightPath(
    vw,
    vh,
    rect.left - HOLE_PADDING,
    rect.top - HOLE_PADDING,
    rect.width + HOLE_PADDING * 2,
    rect.height + HOLE_PADDING * 2,
    HOLE_RADIUS,
  );
  return (
    <svg
      aria-hidden
      data-coach-freeze
      className="fixed inset-0 z-[1000000000] h-full w-full"
      width={vw}
      height={vh}
      viewBox={`0 0 ${vw} ${vh}`}
      style={{ pointerEvents: "none" }}
    >
      <path d={d} fillRule="evenodd" style={{ fill: DIM, pointerEvents: "auto" }} />
    </svg>
  );
}
