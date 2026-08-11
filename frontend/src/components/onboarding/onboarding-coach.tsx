"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { activateTab, spotlightPath, waitForElement } from "@/components/onboarding/spotlight";
import { Button, IconButton } from "@/components/ui";
import { useOnboardingFlow } from "@/hooks/use-onboarding-flow";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { AGENT_BUILDER, pageKey } from "@/lib/onboarding/tour";

/** Space between the control and the freeze layer's cut-out, so the ring plays inside it. */
const HOLE_PADDING = 10;
const HOLE_RADIUS = 12;

/** Space between the control and the highlight ring, so the ring frames rather than traces it. */
const RING_PAD = 6;

/** The side of the dot the ring starts as, before it grows onto the first control. */
const DOT = 12;

/** The dim the freeze layer paints over the frozen page. */
const DIM = "rgba(10, 10, 10, 0.5)";

/** A box in viewport coordinates. */
interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * The target's box tagged with the step it was measured for. The tag is what lets
 * a step change clear the cut-out without a reset call: a rect from the previous
 * step stops matching `stepId` and stops rendering until the new target is found.
 */
interface Rect extends Box {
  stepId: string;
}

/**
 * A floating layer the freeze must step aside for: a modal dialog, or any Radix
 * popper (a popover, dropdown, select or combobox). Both are portalled above the
 * page at a low z-index, so the freeze would otherwise dim the create dialog the
 * step asks the reader to fill, or the knowledge-base picker it asks them to
 * open — the "frozen screen with a ring on it" a reader hit clicking "create new
 * one" inside a picker. Our own card is `role="dialog"` with no `data-state`, so
 * it is not matched here and the freeze does not lift for it.
 */
const OPEN_OVERLAY =
  '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], [data-radix-popper-content-wrapper]';

/**
 * Modal dialogs alone — what an `opened` signal counts. A popper is excluded on
 * purpose: opening a select while on a "now open the form" step must not read
 * as the form opening. Counted rather than tested for presence, so a dialog
 * stacked on an already-open one (the builder's catalog opening the connect
 * form) still reads as an opening.
 */
const OPEN_DIALOG = '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]';

/** A small dot centred in the viewport — where the ring starts each flow before it travels. */
function centerDot(): Box {
  return {
    top: window.innerHeight / 2 - DOT / 2,
    left: window.innerWidth / 2 - DOT / 2,
    width: DOT,
    height: DOT,
  };
}

/** The ring's box for a control: the control's box, grown by `RING_PAD` on every side. */
function ringBoxFor(box: Box): Box {
  return {
    top: box.top - RING_PAD,
    left: box.left - RING_PAD,
    width: box.width + RING_PAD * 2,
    height: box.height + RING_PAD * 2,
  };
}

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
 * The freeze steps aside the moment a floating layer opens (`OPEN_OVERLAY`): a
 * Radix dialog is already modal and dims the page itself, and a popover, dropdown
 * or select is the control the step wants operated — so a second freeze over
 * either would only fight its stacking and re-dim it, the trap that kept the coach
 * driver-less and the one a reader hit opening a picker mid-step. While a layer is
 * up the reader works against Radix's own stacking, and the step advances when its
 * resource appears. Guidance does not stop at the dialog's edge, though: a step
 * marked `inOverlay` points at a field *inside* one — the ring renders over the
 * dialog and frames it — and a step with an `opened` signal advances the moment a
 * dialog opens on top of however many were open when it began (`OPEN_DIALOG` is
 * counted, not tested for presence, so the builder's catalog dialog opening the
 * connect form still reads as an opening).
 *
 * The highlight is a ring that travels and grows from the centre of the screen
 * onto the first control, then from one control to the next — a fixed element so
 * it can animate its own position and size, which the freeze makes safe (nothing
 * scrolls under it, and the control is scrolled into view first). Its size and
 * position are `ringRect`; the CSS transition on those is the travel. The ring
 * re-centres at each fork, so its move out of a `question` is a fresh travel from
 * the middle rather than a slide from wherever the last control sat.
 *
 * A `question` step is a fork rather than a control: the page freezes whole (no
 * cut-out) and the card offers Yes/Skip, `answer` recording the choice and
 * widening the flow to its detour or stepping over it. A fork can instead hand off
 * to another flow — the chat run's "build an agent first?" opens `create-agent`
 * on yes (`opensFlow`) rather than revealing a detour within this one. A detour's
 * return leg is
 * *taught*: its steps point at the sidebar and the agent's own card and wait for
 * the reader's click to land (`signalMet` on an `arrived` signal), the pencil
 * resolved from the id the flow captured so a full gallery still returns to the
 * right agent.
 *
 * Otherwise advancement is the app's, not a button's: a step with a signal ends
 * when its resource appears or its page is reached (`signalMet` from
 * `useOnboardingFlow`), so the reader is never told "now click Next" after doing
 * the thing the step asked for, and carries no button — the doing is the advance.
 * A step with no signal (write instructions, or "here is where it attaches")
 * carries a Next. The close button always ends the flow, because a walkthrough is
 * never worth trapping someone in. Mounted only while a flow runs, so the
 * resource-count queries its hook fires live only then.
 */
export function OnboardingCoach() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const pathname = usePathname();
  const {
    isActive,
    flowId,
    step,
    index,
    steps,
    isLast,
    signalMet,
    next,
    finish,
    answer,
    openFlow,
    flowAgentId,
    setFlowAgentId,
  } = useOnboardingFlow();
  const [rect, setRect] = useState<Rect | null>(null);
  const [ringRect, setRingRect] = useState<Box | null>(null);
  const [ringAnchor, setRingAnchor] = useState<string | null>(null);
  const [overlayOpen, setOverlayOpen] = useState(false);
  const [dialogCount, setDialogCount] = useState(0);
  const [blockRect, setBlockRect] = useState<Rect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const stepId = step?.id;
  const blockSubmit = step?.blockSubmit;

  // The ring re-centres at the start of a flow and again at each fork, so its
  // first move is a travel out from the middle rather than a jump from nowhere.
  // Adjusted during render, guarded on the anchor changing — React's supported
  // reset-on-prop pattern — because an effect that set state here would fire a
  // frame late and trip `react-hooks/set-state-in-effect`. The anchor is a
  // constant across a run's pointer steps (so they travel control-to-control) and
  // a step's own id on a `question` (so leaving the fork re-centres it).
  const anchor = isActive && flowId ? `${flowId}:${step?.question ? stepId : "run"}` : null;
  if (anchor !== null && anchor !== ringAnchor && typeof window !== "undefined") {
    setRingAnchor(anchor);
    setRingRect(centerDot());
  }

  // The freeze must yield to a floating layer the moment one opens and take back
  // over when it closes — watched here rather than polled, so the handover is a
  // frame, not a tick. A popper wrapper is added and removed as a node, which the
  // subtree watch catches; a dialog toggles `data-state`, which the attribute one
  // does.
  useEffect(() => {
    if (!isActive) return;
    const check = () => {
      setOverlayOpen(document.querySelector(OPEN_OVERLAY) !== null);
      setDialogCount(document.querySelectorAll(OPEN_DIALOG).length);
    };
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

  // An `opened` step is met when a dialog opens on top of however many were open
  // as the step began — the baseline, captured the same render-adjusted way the
  // ring anchor is, so a step that starts with the catalog dialog already up
  // waits for the connect form rather than crediting the dialog it arrived in.
  const [dialogBase, setDialogBase] = useState<{ id: string; count: number } | null>(null);
  if (stepId && step?.signal?.kind === "opened" && dialogBase?.id !== stepId) {
    setDialogBase({ id: stepId, count: dialogCount });
  }
  const openedMet =
    step?.signal?.kind === "opened" &&
    dialogBase !== null &&
    dialogBase.id === stepId &&
    dialogCount > dialogBase.count;
  useEffect(() => {
    if (isActive && openedMet) next();
  }, [isActive, openedMet, next]);

  // The agent a create-agent flow builds opens in the builder; capture its id so
  // the model and publish gates can read its draft, and a detour's return leg can
  // point back at that agent's card rather than the first in the gallery. Not
  // while the create step is still showing, though: the flow can start on another
  // agent's `/agents/<id>` — an offer taken from a builder — and capturing there
  // would pin the walk to that agent, a published one sailing straight through the
  // publish gate. Past the create step the only `/agents/<id>` in reach is the
  // draft just made. Once only.
  useEffect(() => {
    if (!isActive || flowId !== "create-agent" || flowAgentId) return;
    if (stepId === "flow-agent-create") return;
    const prefix = `${ROUTES.AGENTS}/`;
    const here = stripLocale(pathname);
    if (!here.startsWith(prefix)) return;
    const id = here.slice(prefix.length).split("/")[0];
    if (id) setFlowAgentId(id);
  }, [isActive, flowId, flowAgentId, stepId, pathname, setFlowAgentId]);

  // Get to the page, reveal the tab that holds the control, find it, scroll it
  // into view, and measure it — for both the freeze cut-out and the ring. The
  // cut-out is repositioned on scroll and resize until the step changes or the
  // flow ends.
  useEffect(() => {
    if (!isActive || !step) return;
    const controller = new AbortController();
    const { signal } = controller;
    const here = stripLocale(pathname);
    const sid = step.id;

    void (async () => {
      // Real routes are navigable directly. The builder's pseudo-identity
      // (`AGENT_BUILDER`) is navigable too once the flow has captured which agent
      // it built: a fork that crossed to another section to ask its question
      // leaves the reader there on Skip, and the next builder step must be able to
      // carry them back rather than hunt for its control on the wrong page under a
      // full-screen freeze. Before the id exists (the create step) the coach
      // waits instead — the app's own navigation into the builder is what arrives.
      if (step.page === AGENT_BUILDER && pageKey(here) !== AGENT_BUILDER && flowAgentId) {
        router.push(`${ROUTES.AGENTS}/${flowAgentId}`);
        return; // this effect re-runs once the navigation lands
      }
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
      // A dynamic step points at the very agent this flow created, resolved from
      // the captured id; a plain one at its fixed `data-tour`. Without the id yet
      // (it is captured on the builder, before any return leg) the dynamic
      // selector falls back to the first such control rather than hunting forever.
      const selector =
        step.dynamicTarget === "createdAgentEdit"
          ? `[data-tour="agent-card-edit"]${flowAgentId ? `[data-agent-id="${flowAgentId}"]` : ""}`
          : `[data-tour="${step.target}"]`;
      // No timeout: a coach target must appear, not be skipped. A fixed deadline
      // that lapsed on a cold query or a slow builder left the freeze full-viewport
      // with no cut-out and no Next — closing the flow the only way out. The abort
      // on step change or flow end already bounds this wait.
      const target = await waitForElement(selector, signal, null);
      if (signal.aborted || !(target instanceof HTMLElement)) return;

      target.scrollIntoView({ block: "center", inline: "center" });
      const place = () => {
        const b = target.getBoundingClientRect();
        const box = { top: b.top, left: b.left, width: b.width, height: b.height };
        setRect({ stepId: sid, ...box });
        setRingRect(ringBoxFor(box));
      };
      place();
      // Measure again once layout has settled. A control measured a frame too
      // early — or before its webfont swaps in and changes its width, which moves
      // the left edge of a right-aligned button — leaves the ring and cut-out
      // off-centre. A frame later catches the first; a size observer on the
      // control and on the body catches the font swap and any reflow that shifts
      // it. The CSS transition on the ring makes each correction a glide, not a jump.
      const raf = requestAnimationFrame(place);
      const observer = new ResizeObserver(place);
      observer.observe(target);
      observer.observe(document.body);
      window.addEventListener("scroll", place, true);
      window.addEventListener("resize", place);
      signal.addEventListener("abort", () => {
        cancelAnimationFrame(raf);
        observer.disconnect();
        window.removeEventListener("scroll", place, true);
        window.removeEventListener("resize", place);
      });
    })();

    return () => controller.abort();
  }, [isActive, step, stepId, pathname, router, flowAgentId]);

  // Track the control this step keeps click-blocked (`blockSubmit`), so the guard
  // over it follows the dialog as it reflows. Its own box, not the target's: the
  // step points at a field while blocking the submit button somewhere else in the
  // dialog. Tagged with the step it was measured for, the same way `rect` is, so a
  // step that names none — the one that finally points at the submit — stops
  // matching and the guard lifts without an effect clearing state.
  useEffect(() => {
    if (!isActive || !blockSubmit || !stepId) return;
    const sid = stepId;
    const controller = new AbortController();
    const { signal } = controller;
    void (async () => {
      const el = await waitForElement(`[data-tour="${blockSubmit}"]`, signal);
      if (signal.aborted || !(el instanceof HTMLElement)) return;
      const place = () => {
        const b = el.getBoundingClientRect();
        setBlockRect({ stepId: sid, top: b.top, left: b.left, width: b.width, height: b.height });
      };
      place();
      const observer = new ResizeObserver(place);
      observer.observe(el);
      observer.observe(document.body);
      window.addEventListener("scroll", place, true);
      window.addEventListener("resize", place);
      signal.addEventListener("abort", () => {
        observer.disconnect();
        window.removeEventListener("scroll", place, true);
        window.removeEventListener("resize", place);
      });
    })();
    return () => controller.abort();
  }, [isActive, blockSubmit, stepId]);

  // The submit guard swallows pointer clicks, but the keyboard walks past it: Enter
  // in a create dialog's text field submits the form, and Enter on its focused
  // submit button activates it — either creates the resource steps early, and its
  // later field steps then baseline after the creation and never advance, leaving
  // the reader dead-ended. While a `blockSubmit` step shows, cancel that Enter in
  // the capture phase, before the field or button sees it. A text `<input>` and the
  // guarded submit are the only two paths blocked: a textarea, the source editor
  // (`isContentEditable`) and a Radix select keep Enter for newlines and choosing.
  useEffect(() => {
    if (!isActive || !blockSubmit) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Enter") return;
      const el = event.target as HTMLElement | null;
      if (!el) return;
      const submitsForm = el instanceof HTMLInputElement;
      const activatesSubmit = el.closest(`[data-tour="${blockSubmit}"]`) !== null;
      if (submitsForm || activatesSubmit) event.preventDefault();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [isActive, blockSubmit]);

  // While the freeze is up the card is the only modal surface, so move focus to it
  // on each step — a screen reader then announces the new instruction and a keyboard
  // user starts there rather than wherever focus was stranded on the frozen page. A
  // dialog or picker open over the page manages its own focus, so this yields to it.
  useEffect(() => {
    if (!isActive || !step) return;
    const frozen = !step.roam && !step.inOverlay && !overlayOpen;
    if (frozen) cardRef.current?.focus();
  }, [isActive, step, overlayOpen]);

  // Escape ends the walk when the page is frozen — the keyboard equal of the close
  // button, the frozen page having nothing else Escape could act on. With a dialog
  // or picker open, Radix owns Escape (and `dialog.tsx` keeps that dialog from
  // closing under the coach), so it is left to them.
  useEffect(() => {
    if (!isActive) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.querySelector(OPEN_OVERLAY)) return;
      finish();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [isActive, finish]);

  // The resource appeared — the reader did the thing. Advance, or end the flow if
  // this was the last step.
  useEffect(() => {
    if (isActive && signalMet) next();
  }, [isActive, signalMet, next]);

  if (!isActive || !step) return null;

  // A fork freezes the page whole and shows no ring; a pointer step cuts a hole
  // over its control and rings it; a `roam` step does neither, because the reader
  // is choosing one of many and a hole over one would lock the choice. The tag on
  // `rect` clears a stale hole between steps: a rect measured for the previous step
  // stops matching `stepId`. An in-overlay step never freezes (the dialog's own
  // modal overlay dims the page) and rings only while the dialog is up, so closing
  // it mid-walk leaves the page usable to reopen it rather than ringing where a
  // field used to be — and it can still hold a `blockSubmit` guard over the
  // dialog's own submit until the walk reaches it.
  const isQuestion = !!step.question;
  const inOverlay = !!step.inOverlay;
  const roam = !!step.roam;
  const frozen = !roam && !inOverlay && !overlayOpen;
  const current = isQuestion ? null : rect?.stepId === stepId ? rect : null;

  return (
    <>
      {!roam && !overlayOpen && !inOverlay && <FreezeLayer rect={current} />}
      {!roam && (inOverlay ? overlayOpen : !overlayOpen) && !isQuestion && ringRect && (
        <div
          aria-hidden
          data-coach-ring
          className="onboarding-coach-ring"
          style={{
            top: ringRect.top,
            left: ringRect.left,
            width: ringRect.width,
            height: ringRect.height,
          }}
        />
      )}
      {/* Sits over the dialog's submit while an earlier field step shows, swallowing
          the click that would create before the walk reaches the last field. It needs
          pointer events of its own — a modal dialog turns the body's off. Lifts on the
          step that points at the submit, which names no `blockSubmit`. */}
      {blockSubmit && blockRect && blockRect.stepId === stepId && (
        <div
          aria-hidden
          data-coach-submit-guard
          className="pointer-events-auto fixed z-[1000000001]"
          style={{
            top: blockRect.top,
            left: blockRect.left,
            width: blockRect.width,
            height: blockRect.height,
            cursor: "not-allowed",
          }}
        />
      )}
      {/* A modal Radix dialog sets pointer-events:none on the body while it is open,
          and this card sits outside that dialog — so it re-enables them for itself, or
          its own Next and close inherit none and go inert while guiding a field inside a
          create dialog. `onInteractOutside` on DialogContent keeps the click from also
          dismissing that dialog. */}
      <div
        ref={cardRef}
        data-coach-card
        role="dialog"
        aria-modal={frozen ? true : undefined}
        aria-label={t(`steps.${step.id}.title`)}
        tabIndex={-1}
        className="bg-popover text-popover-foreground pointer-events-auto fixed bottom-6 left-1/2 z-[1000000002] w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border p-4 shadow-lg outline-none"
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
        {isQuestion ? (
          <div className="mt-3 flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => answer(step.id, "skip")}>
              {t("coachSkip")}
            </Button>
            <Button
              size="sm"
              onClick={() => (step.opensFlow ? openFlow(step.opensFlow) : answer(step.id, "yes"))}
            >
              {t("coachYes")}
            </Button>
          </div>
        ) : (
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
        )}
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
