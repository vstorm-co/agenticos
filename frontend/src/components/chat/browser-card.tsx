"use client";

import { Globe } from "lucide-react";
import { useTranslations } from "next-intl";

import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { OUTCOME_TONE } from "./browser-view";
import { hostOf } from "./browser-window";

/**
 * Every browse of the turn, one line each, under the message that started it.
 *
 * A line rather than a window: the browser has its own column beside the
 * conversation, and the transcript only has to say that the agent is browsing,
 * where, and whether it needs somebody - with the way to look.
 */
export function BrowserCards({ browses }: { browses: Browse[] }) {
  if (browses.length === 0) return null;
  return (
    <div className="ml-10 flex max-w-2xl flex-col gap-2 pb-2 sm:ml-[52px]">
      {browses.map((browse) => (
        <BrowserLine key={browse.callId} browse={browse} />
      ))}
    </div>
  );
}

/** One browse in the transcript: a thumbnail, where it is, and the way to watch it. */
function BrowserLine({ browse }: { browse: Browse }) {
  const t = useTranslations("chat");
  const open = useBrowserPanelStore((state) => state.open);
  const openCallId = useBrowserPanelStore((state) => state.openCallId);
  const running = isRunning(browse);
  const host = hostOf(browse.url);
  const needs = running ? browse.needs : null;
  const latest = browse.steps.at(-1);
  const showing = openCallId === browse.callId;

  return (
    <button
      type="button"
      onClick={() => open(browse.callId, "panel")}
      aria-label={t("browserOpenPanel")}
      className={cn(
        "group flex w-full min-w-0 items-center gap-3 rounded-2xl px-2.5 py-2 text-left transition-colors",
        needs
          ? "bg-amber-500/12 hover:bg-amber-500/18"
          : "bg-foreground/[0.04] hover:bg-foreground/[0.07]",
      )}
    >
      <span className="ring-foreground/10 bg-background relative flex h-10 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg ring-1">
        {browse.image ? (
          // eslint-disable-next-line @next/next/no-img-element -- a data: URL from this run's own socket.
          <img src={browse.image} alt="" className="h-full w-full object-cover object-top" />
        ) : (
          <Globe className="text-muted-foreground size-4" aria-hidden />
        )}
        {running && (
          <span className="absolute top-1 right-1 size-1.5 rounded-full bg-emerald-500 ring-2 ring-white" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-foreground block truncate text-sm font-medium">
          {host
            ? running
              ? t("browserLineBrowsing", { host })
              : t("browserLineBrowsed", { host })
            : t("browserStarting")}
        </span>
        <span
          className={cn(
            "block truncate text-xs",
            needs
              ? "font-medium text-amber-800 dark:text-amber-300"
              : browse.outcome
                ? OUTCOME_TONE[browse.outcome]
                : "text-muted-foreground",
          )}
        >
          {needs ? (
            t("browserLineNeeds", { what: needs })
          ) : browse.outcome ? (
            t(`browserOutcome.${browse.outcome}`)
          ) : latest ? (
            <>
              {t("browserAction", { operation: latest.operation })}
              {/* Page-derived text, rendered as text. */}
              {latest.target && <span className="opacity-75"> {latest.target}</span>}
            </>
          ) : (
            t("browserStarting")
          )}
        </span>
      </span>
      <span
        className={cn(
          "shrink-0 rounded-full px-2.5 py-1 text-xs font-medium",
          needs
            ? "bg-foreground text-background"
            : "text-muted-foreground group-hover:text-foreground",
        )}
      >
        {needs ? t("browserTakeOver") : showing ? t("browserLineShowing") : t("browserLineOpen")}
      </span>
    </button>
  );
}
