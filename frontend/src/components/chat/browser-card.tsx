"use client";

import { ArrowUpRight, Globe } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useContext } from "react";

import { isRunning, type Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import type { ToolCall } from "@/types";
import { OUTCOME_TONE } from "./browser-view";
import { hostOf } from "./browser-window";

/** The browses running in this chat, by call - what a turn's `browse_web` steps draw live. */
const LiveBrowses = createContext<Browse[]>([]);

/** Hands the chat's live browses to the turns that made them. */
export const LiveBrowsesProvider = LiveBrowses.Provider;

/**
 * A turn's browses, one line each, where the turn made them.
 *
 * Part of the turn rather than a strip under the whole transcript: drawn there,
 * a finished browse sat under the answer's footer, misaligned with the message,
 * and vanished with the next message, because the strip only knew the turn in
 * flight. Here each `browse_web` call draws its own line - live while the
 * browse is in this chat's socket, with the way to watch it; as a record once
 * it is not, with the way to the site.
 */
export function TurnBrowses({ calls }: { calls: ToolCall[] }) {
  const live = useContext(LiveBrowses);
  if (calls.length === 0) return null;
  return (
    <div className="flex max-w-2xl flex-col gap-2 py-1">
      {calls.map((call) => {
        const browse = live.find((entry) => entry.callId === call.id);
        return browse ? (
          <BrowserLine key={call.id} browse={browse} />
        ) : (
          <RecordedBrowse key={call.id} call={call} />
        );
      })}
    </div>
  );
}

/** A browse from an earlier turn: where it went, and the way there. */
function RecordedBrowse({ call }: { call: ToolCall }) {
  const t = useTranslations("chat");
  const start = typeof call.args.start_url === "string" ? call.args.start_url : null;
  const host = hostOf(start);
  return (
    <div className="bg-foreground/[0.04] flex w-full min-w-0 items-center gap-3 rounded-2xl px-2.5 py-2">
      <span className="ring-foreground/10 bg-background flex h-10 w-14 shrink-0 items-center justify-center rounded-lg ring-1">
        <Globe className="text-muted-foreground size-4" aria-hidden />
      </span>
      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
        {host ? t("browserLineBrowsed", { host }) : t("browserLineBrowsedWeb")}
      </span>
      {start && host && (
        <a
          href={start}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
        >
          {t("browserVisitSite")}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </a>
      )}
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
