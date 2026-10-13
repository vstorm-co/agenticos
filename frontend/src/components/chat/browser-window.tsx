"use client";

import { useEffect, useRef, useState } from "react";
import {
  ExternalLink,
  Globe,
  Hand,
  ListChecks,
  Lock,
  Maximize2,
  Minimize2,
  Undo2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type { BrowserCommand } from "@/hooks/use-live-browse";
import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { OperationIcon, OUTCOME_TONE, StepTimeline } from "./browser-view";
import { LiveViewport } from "./live-viewport";

/** What a person may do with the browser, as the window offers it. */
export interface BrowseControl {
  /** Whether this person may drive the browser at all - the server's answer. */
  canControl: boolean;
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
        "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.07] flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors",
        pressed && "text-foreground bg-foreground/[0.07]",
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
  const me = user?.full_name || user?.email || "";
  const [asked, setAsked] = useState(false);
  const holding = Boolean(browse.heldBy) && browse.heldBy === me;
  return {
    holding,
    someoneElse: Boolean(browse.heldBy) && !holding,
    waiting: asked && !browse.heldBy && isRunning(browse),
    takeOver: () => {
      setAsked(true);
      control?.send({ type: "take_over" });
    },
    giveBack: () => {
      setAsked(false);
      control?.send({ type: "give_back" });
    },
  };
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
  return ref;
}

/**
 * The agent's browser, drawn as a browser: a tab, an address bar, the page.
 *
 * The one view of a browse. The chat docks it beside the conversation and the
 * link a channel posts opens it on a page of its own - so what somebody watches,
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
}: {
  browse: Browse;
  control: BrowseControl | null;
  onClose?: () => void;
  maximized?: boolean;
  onMaximize?: () => void;
  /** Where the same browse opens on a page of its own, where that is somewhere else. */
  newTabHref?: string;
}) {
  const t = useTranslations("chat");
  const tb = useTranslations("browse");
  const [showSteps, setShowSteps] = useState(false);
  const hold = useHold(browse, control);
  const running = isRunning(browse);
  const host = hostOf(browse.url);
  const secure = browse.url?.startsWith("https:") ?? false;
  const canDrive = running && control !== null && control.canControl;
  const pageRef = useFitPage(canDrive ? control : null);

  return (
    <section
      aria-label={t("browserHeading")}
      className="bg-muted/60 flex h-full min-h-0 flex-col dark:bg-neutral-900"
    >
      <div className="flex items-center gap-1 px-2 pt-2">
        <div className="bg-background flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 sm:max-w-[70%] sm:flex-none">
          {secure ? (
            <Lock className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          ) : (
            <Globe className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          )}
          <h2 className="text-foreground min-w-0 truncate text-sm font-medium">
            {browse.title || host || t("browserHeading")}
          </h2>
          {running && (
            <span
              className="size-1.5 shrink-0 rounded-full bg-emerald-500"
              aria-label={t("browserLive")}
            />
          )}
        </div>
        <div className="flex-1" />
        {onMaximize && (
          <ChromeButton
            label={maximized ? t("browserRestore") : t("browserMaximize")}
            onClick={onMaximize}
            // A phone already gives the window the screen.
            className="max-lg:hidden"
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

      <div className="flex items-center gap-1.5 px-2 py-2">
        <div
          className="bg-background text-muted-foreground flex h-9 min-w-0 flex-1 items-center justify-center rounded-xl px-3 text-sm"
          title={browse.url ?? undefined}
        >
          <span className="truncate">
            {host ? (
              <span className="text-foreground font-medium">{host}</span>
            ) : (
              t("browserStarting")
            )}
          </span>
        </div>
        {canDrive &&
          (hold.holding ? (
            <button
              type="button"
              onClick={hold.giveBack}
              className="bg-foreground text-background hover:bg-foreground/90 flex h-9 shrink-0 items-center gap-1.5 rounded-xl px-3 text-sm font-medium"
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
              className="bg-background text-foreground hover:bg-background/70 flex h-9 shrink-0 items-center gap-1.5 rounded-xl px-3 text-sm font-medium disabled:opacity-60"
            >
              <Hand className="size-4" aria-hidden />
              {hold.waiting ? tb("takingOver") : tb("takeOver")}
            </button>
          ))}
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
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.07] flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors"
          >
            <ExternalLink className="size-4" aria-hidden />
          </a>
        )}
      </div>

      {browse.needs && running && (
        <div className="mx-2 mb-2 rounded-xl bg-amber-500/15 px-3 py-2 text-sm">
          <span className="font-medium text-amber-800 dark:text-amber-300">{tb("needsYou")}</span>{" "}
          {/* Model-written - rendered as text. */}
          <span className="text-foreground/80">{browse.needs}</span>
        </div>
      )}
      {browse.heldBy && !hold.holding && running && (
        <p className="text-muted-foreground mx-2 mb-2 px-1 text-xs">
          {tb("heldBy", { name: browse.heldBy })}
        </p>
      )}

      {/* The page, edge to edge, the way a browser draws one: the window has
          asked for the page to be laid out at its own size (see `useFitPage`),
          so the picture fills it 1:1 rather than being a laptop screen shrunk
          into a column. What the browser is doing floats over the bottom. */}
      <div ref={pageRef} className="bg-background relative min-h-0 flex-1 overflow-hidden">
        <div className="h-full scrollbar-thin overflow-y-auto">
          {browse.image ? (
            <LiveViewport
              browse={browse}
              holding={hold.holding}
              onCommand={(command) => control?.send(command)}
              flush
            />
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
