"use client";

import { useEffect, useRef, useState } from "react";
import {
  ExternalLink,
  Globe,
  Hand,
  ListChecks,
  Lock,
  Maximize2,
  MessageSquarePlus,
  Minimize2,
  Undo2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { BrowserCommand } from "@/hooks/use-live-browse";
import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { BrowserCommentLayer, type PageComment } from "./browser-comment";
import { OperationIcon, OUTCOME_TONE, StepTimeline } from "./browser-view";
import { LiveViewport } from "./live-viewport";

/** What a person may do with the browser, as the window offers it. */
export interface BrowseControl {
  /** Whether this person may drive the browser at all - the server's answer. */
  canControl: boolean;
  /** Whether a sign-in they make while holding it may be kept for later browses (#2129). */
  canRemember?: boolean;
  send: (command: BrowserCommand) => void;
}

/** The host a browse is on, or null before it has a page. */
export function hostOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** What follows the host in the address bar - the path and query - or "" at the root or for an address that is not a URL. */
function pathOf(url: string): string {
  try {
    const parsed = new URL(url);
    const rest = `${parsed.pathname}${parsed.search}`;
    return rest === "/" ? "" : rest;
  } catch {
    return "";
  }
}

/** One square control in the window's chrome. */
function ChromeButton({
  label,
  onClick,
  pressed,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={cn(
        "text-foreground/70 hover:text-foreground hover:bg-foreground/[0.08] flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors",
        pressed && "text-foreground bg-foreground/[0.08]",
        className,
      )}
    >
      {children}
    </button>
  );
}

/**
 * Who holds the browser and how to change that, for this person.
 *
 * `asked` covers the gap between pressing Take over and the browser answering:
 * the agent finishes the step in flight first, and a button that stayed live
 * through that would be pressed again.
 */
function useHold(browse: Browse, control: BrowseControl | null) {
  const user = useAuthStore((state) => state.user);
  const [asked, setAsked] = useState(false);
  // By id: two viewers can share a name, and each would read the other's hold
  // as their own and get the page's live controls.
  const holding = Boolean(browse.heldById) && browse.heldById === user?.id;
  return {
    holding,
    someoneElse: Boolean(browse.heldBy) && !holding,
    waiting: asked && !browse.heldBy && isRunning(browse),
    takeOver: () => {
      setAsked(true);
      control?.send({ type: "take_over" });
    },
    giveBack: (remember: boolean) => {
      setAsked(false);
      control?.send({ type: "give_back", remember });
    },
  };
}

/**
 * The agent's pointer, where it is about to press - as a desktop agent shows it.
 *
 * Positioned in fractions of the picture, so it lands on the same element at
 * whatever size the picture is drawn. It glides from the last place it pressed
 * to the next, labelled the way a collaborator's cursor is, and each step draws
 * a ring that opens and fades, keyed on the step so a second press on the same
 * spot still shows. The ring holds its last frame - invisible - rather than
 * snapping back: without that it stayed on the page as a blue disc.
 */
export function AgentCursor({ pointer }: { pointer: { x: number; y: number; step: number } }) {
  const t = useTranslations("chat");
  return (
    <span
      aria-hidden
      data-testid="agent-cursor"
      className="pointer-events-none absolute z-10 transition-[left,top] duration-500 ease-out motion-reduce:transition-none"
      style={{ left: `${pointer.x * 100}%`, top: `${pointer.y * 100}%` }}
    >
      <span
        key={pointer.step}
        className="absolute -top-5 -left-5 size-10 rounded-full border-2 border-sky-500 opacity-0 motion-safe:animate-[agent-click_650ms_ease-out_1_forwards]"
      />
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        className="relative -translate-x-[2px] -translate-y-[1px] drop-shadow-[0_1px_2px_rgba(0,0,0,0.4)]"
      >
        <path
          d="M4 2.5 L4 19.5 L8.6 15.2 L11.6 21.5 L14.4 20.2 L11.5 14.1 L17.8 14.1 Z"
          fill="#0ea5e9"
          stroke="#fff"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
      <span className="absolute top-4 left-3 rounded-full bg-sky-500 px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-white shadow-md">
        {t("browserAgentCursor")}
      </span>
    </span>
  );
}

/**
 * What the browser is doing this moment, floating over the bottom of the page.
 *
 * The one line of the trace worth a glance while it runs - the whole list is a
 * button away - and how it ended once it has.
 */
function StatusPill({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  const latest = browse.steps.at(-1);
  if (browse.outcome) {
    return (
      <span
        className={cn(
          "bg-background ring-foreground/10 rounded-full px-3 py-1.5 text-xs font-medium shadow-lg ring-1",
          OUTCOME_TONE[browse.outcome],
        )}
        data-testid="browse-outcome"
      >
        {t(`browserOutcome.${browse.outcome}`)}
      </span>
    );
  }
  return (
    <span className="bg-foreground text-background flex max-w-full min-w-0 items-center gap-2 rounded-full px-3 py-1.5 text-xs shadow-lg">
      <span className="relative flex size-1.5 shrink-0" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-70" />
        <span className="relative inline-flex size-1.5 rounded-full bg-emerald-400" />
      </span>
      {latest ? (
        <>
          <OperationIcon operation={latest.operation} className="size-3.5 shrink-0" />
          <span className="shrink-0 font-medium">
            {t("browserAction", { operation: latest.operation })}
          </span>
          {/* Page-derived text, rendered as text. */}
          {latest.target && <span className="truncate opacity-75">{latest.target}</span>}
        </>
      ) : (
        <span className="font-medium">{t("browserStarting")}</span>
      )}
    </span>
  );
}

/** How long the window must keep a size before the page is laid out again. */
const FIT_SETTLE_MS = 250;

/**
 * Asks the browser to lay the page out at the size of the window showing it.
 *
 * What makes this a browser rather than a thumbnail: the site's own layout runs
 * for this window, and the picture comes back at its size and density, drawn
 * 1:1. Sent only by someone who may drive the browse - the size is the tab's,
 * shared by everyone watching - and after the window has kept a size for a
 * moment, so dragging the panel's edge does not lay the page out sixty times.
 * The browser applies it between steps.
 */
function useFitPage(control: BrowseControl | null) {
  const ref = useRef<HTMLDivElement>(null);
  const [asked, setAsked] = useState<number | null>(null);
  const send = control?.send;
  useEffect(() => {
    const element = ref.current;
    if (!element || !send) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let last = "";
    const fit = () => {
      const width = Math.max(320, Math.round(element.clientWidth));
      const height = Math.max(320, Math.round(element.clientHeight));
      const scale: 1 | 2 = window.devicePixelRatio >= 1.5 ? 2 : 1;
      const size = `${width}x${height}@${scale}`;
      if (size === last) return;
      last = size;
      setAsked(width * scale);
      send({ type: "resize", width, height, scale });
    };
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(fit, FIT_SETTLE_MS);
    });
    observer.observe(element);
    fit();
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [send]);
  return { ref, asked };
}

/** How long a window waits for a picture of its own size before showing what it has. */
const FIRST_FIT_MS = 6000;

/**
 * Whether the picture can be shown: once a frame has arrived at the width this
 * window asked for, or once waiting for one has taken too long.
 *
 * The browser opens the tab at a default size and the window's own arrives a
 * moment later, applied between the agent's steps - so the first frames are a
 * wider page shrunk into the column, small type that snaps to the real layout
 * when the right size lands. Holding the picture back until then is the
 * difference between a browser opening and a thumbnail being swapped. Latched:
 * once shown, a later frame of another size (the window resized) shows too.
 */
function useFitted(image: string | null, asked: number | null, waiting: boolean): boolean {
  const [fitted, setFitted] = useState(false);
  useEffect(() => {
    if (!waiting || fitted) return;
    const timer = setTimeout(() => setFitted(true), FIRST_FIT_MS);
    return () => clearTimeout(timer);
  }, [waiting, fitted]);
  useEffect(() => {
    if (!waiting || fitted || asked === null || !image) return;
    const probe = new Image();
    probe.onload = () => {
      // Within a couple of pixels: a scrollbar or rounding is not a wrong size.
      if (Math.abs(probe.naturalWidth - asked) <= 2) setFitted(true);
    };
    probe.src = image;
  }, [image, asked, waiting, fitted]);
  return fitted || !waiting;
}

/**
 * The agent's browser, drawn as a browser: a tab, an address bar, the page.
 *
 * The one view of a browse. The chat draws it under the agent's message (and
 * full screen when somebody maximises it), and the link a channel posts opens it
 * on a page of its own - so what somebody watches,
 * and where they take over, is the same window wherever they arrived from. The
 * page has the room; what the agent is doing is one line over it, and the full
 * list of steps is folded behind a button, because people watching a browse look
 * at the page, not at a log.
 *
 * `control` is null where nobody can drive this browse from here: a finished
 * one, or one whose run is not known yet.
 */
export function BrowserWindow({
  browse,
  control,
  onClose,
  maximized,
  onMaximize,
  newTabHref,
  waitForFit = false,
  onComment,
}: {
  browse: Browse;
  control: BrowseControl | null;
  onClose?: () => void;
  maximized?: boolean;
  onMaximize?: () => void;
  /** Where the same browse opens on a page of its own, where that is somewhere else. */
  newTabHref?: string;
  /** Hold the picture back until a frame of this window's size arrives - see `useFitted`. */
  waitForFit?: boolean;
  /** Where a comment on a spot of the page goes - the chat's composer; none, no button. */
  onComment?: (comment: PageComment) => void;
}) {
  const t = useTranslations("chat");
  const tb = useTranslations("browse");
  const [showSteps, setShowSteps] = useState(false);
  const [remember, setRemember] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const hold = useHold(browse, control);
  const running = isRunning(browse);
  const host = hostOf(browse.url);
  const secure = browse.url?.startsWith("https:") ?? false;
  const canDrive = running && control !== null && control.canControl;
  const { ref: pageRef, asked } = useFitPage(canDrive ? control : null);
  const fitted = useFitted(browse.image, asked, waitForFit && canDrive);
  // Pointing at the page and driving it are two gestures on one picture; while
  // somebody holds the tab, a click is theirs to send to it.
  const canComment = onComment !== undefined && browse.image !== null && fitted && !hold.holding;

  return (
    <section
      aria-label={t("browserHeading")}
      className="bg-background flex h-full min-h-0 flex-col"
    >
      {/* One toolbar, the way a browser draws its chrome: the address with the
          page's lock and whether it is live, then what a person can do. A tab
          strip above it held one tab that could not be switched, and read as a
          second address bar. */}
      <div className="bg-background border-border flex h-12 shrink-0 items-center gap-1 border-b px-2">
        <div
          className="bg-muted/80 flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 text-sm"
          title={browse.url ?? undefined}
        >
          {secure ? (
            <Lock className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          ) : (
            <Globe className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          )}
          <h2 className="sr-only">{browse.title || host || t("browserHeading")}</h2>
          <span className="min-w-0 flex-1 truncate">
            {host ? (
              <>
                <span className="text-foreground font-medium">{host}</span>
                <span className="text-muted-foreground">{pathOf(browse.url ?? "")}</span>
              </>
            ) : (
              <span className="text-muted-foreground">{t("browserStarting")}</span>
            )}
          </span>
          {running && (
            <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
              <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden />
              {t("browserLive")}
            </span>
          )}
        </div>
        {canDrive &&
          (hold.holding ? (
            <button
              type="button"
              onClick={() => {
                hold.giveBack(remember);
                // Consent to keep a sign-in is for this hand-back only; the next
                // take-over asks again rather than inheriting a tick.
                setRemember(false);
              }}
              className="bg-foreground text-background hover:bg-foreground/90 flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium"
            >
              <Undo2 className="size-4" aria-hidden />
              {tb("giveBack")}
            </button>
          ) : hold.someoneElse ? null : (
            <button
              type="button"
              onClick={hold.takeOver}
              disabled={hold.waiting}
              title={tb("takeOverHint")}
              className="bg-foreground text-background hover:bg-foreground/90 flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium disabled:opacity-60"
            >
              <Hand className="size-4" aria-hidden />
              {hold.waiting ? tb("takingOver") : tb("takeOver")}
            </button>
          ))}
        {canComment && (
          <ChromeButton
            label={t("browserComment")}
            onClick={() => setCommenting((on) => !on)}
            pressed={commenting}
          >
            <MessageSquarePlus className="size-4" />
          </ChromeButton>
        )}
        <ChromeButton
          label={t("browserShowSteps", { count: browse.steps.length })}
          onClick={() => setShowSteps((shown) => !shown)}
          pressed={showSteps}
        >
          <ListChecks className="size-4" />
        </ChromeButton>
        {newTabHref && (
          <a
            href={newTabHref}
            target="_blank"
            rel="noreferrer"
            aria-label={t("browserOpenNewTab")}
            title={t("browserOpenNewTab")}
            className="text-foreground/70 hover:text-foreground hover:bg-foreground/[0.08] flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors"
          >
            <ExternalLink className="size-4" aria-hidden />
          </a>
        )}
        {onMaximize && (
          <ChromeButton
            label={maximized ? t("browserRestore") : t("browserMaximize")}
            onClick={onMaximize}
          >
            {maximized ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </ChromeButton>
        )}
        {onClose && (
          <ChromeButton label={t("browserClose")} onClick={onClose}>
            <X className="size-4" />
          </ChromeButton>
        )}
      </div>

      {/* While holding: keep the sign-in made here for later browses, offered
          only to the person the run acts for - the server says who that is. */}
      {hold.holding && control?.canRemember && host && (
        <label className="border-border flex cursor-pointer items-center gap-2 border-b px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
            className="accent-foreground size-4"
          />
          <span>{tb("rememberSignIn", { site: host })}</span>
        </label>
      )}
      {browse.kept && !hold.holding && (
        <p className="text-muted-foreground border-border border-b px-3 py-1.5 text-xs">
          {tb("signInKept", { site: browse.kept })}
        </p>
      )}
      {browse.needs && running && (
        <div className="border-border border-b bg-amber-500/15 px-3 py-2 text-sm">
          <span className="font-medium text-amber-800 dark:text-amber-300">{tb("needsYou")}</span>{" "}
          {/* Model-written - rendered as text. */}
          <span className="text-foreground/80">{browse.needs}</span>
        </div>
      )}
      {browse.heldBy && !hold.holding && running && (
        <p className="text-muted-foreground border-border border-b px-3 py-1.5 text-xs">
          {tb("heldBy", { name: browse.heldBy })}
        </p>
      )}

      {/* The page, edge to edge, the way a browser draws one: the window has
          asked for the page to be laid out at its own size (see `useFitPage`),
          so the picture fills it 1:1 rather than being a laptop screen shrunk
          into a column. What the browser is doing floats over the bottom. */}
      <div ref={pageRef} className="bg-background relative min-h-0 flex-1 overflow-hidden">
        <div className="h-full scrollbar-thin overflow-y-auto">
          {browse.image && fitted ? (
            // The comment picker sits beside the remote screen rather than inside
            // it: a form within `role="application"` is one a screen reader
            // cannot reach.
            <div className="relative">
              <LiveViewport
                browse={browse}
                holding={hold.holding}
                onCommand={(command) => control?.send(command)}
                flush
                overlay={
                  running && browse.pointer && !hold.holding ? (
                    <AgentCursor pointer={browse.pointer} />
                  ) : null
                }
              />
              {commenting && canComment && onComment && (
                <BrowserCommentLayer
                  image={browse.image}
                  url={browse.url}
                  onComment={onComment}
                  onDone={() => setCommenting(false)}
                />
              )}
            </div>
          ) : (
            <div className="text-muted-foreground flex h-full items-center justify-center p-6 text-center text-sm">
              {running ? t("browserWaitingForFrame") : t("browserNoPreview")}
            </div>
          )}
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-4">
          {hold.holding ? (
            <span className="rounded-full bg-sky-600 px-3 py-1.5 text-xs font-medium text-white shadow-lg">
              {t("browserHolding")}
            </span>
          ) : (
            <StatusPill browse={browse} />
          )}
        </div>
      </div>

      {showSteps && (
        <div className="bg-background border-border max-h-[40%] min-h-0 scrollbar-thin space-y-3 overflow-y-auto border-t p-4">
          {browse.goal && (
            <p className="text-foreground/80 text-sm leading-relaxed">
              <span className="text-muted-foreground font-medium">{t("browserGoal")} · </span>
              {browse.goal}
            </p>
          )}
          {browse.detail && (
            <p className="text-muted-foreground text-xs leading-relaxed">{browse.detail}</p>
          )}
          {browse.steps.length > 0 ? (
            <StepTimeline browse={browse} />
          ) : (
            <p className="text-muted-foreground text-sm">{t("browserNoSteps")}</p>
          )}
        </div>
      )}
    </section>
  );
}
