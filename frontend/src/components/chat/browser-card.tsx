"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { createContext, useContext } from "react";

import { Maximize2, Monitor } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLiveBrowse } from "@/hooks/use-live-browse";
import {
  DESKTOP_TOOLS,
  recordedBrowserPage,
  turnBrowseVisits,
  isRunning,
  withLivePreview,
  type Browse,
} from "@/lib/browse";
import { cn } from "@/lib/utils";
import { useBrowserPanelStore, type BrowseSurface } from "@/stores/browser-panel-store";
import { selectedWorkspaceBrowse } from "@/lib/workspace-panels";
import type { ToolCall } from "@/types";
import type { PageComment } from "./browser-comment";
import { BrowserWindow, hostOf } from "./browser-window";
import { BrowserVisit } from "./browser-visit";

/** The browses running in this chat, and where a comment on one of their pages goes. */
const LiveBrowses = createContext<{
  browses: Browse[];
  onComment?: (comment: PageComment) => void;
  surfaces?: ReadonlyMap<string, BrowseSurface>;
}>({ browses: [] });

function isDesktop(call: ToolCall): boolean {
  return DESKTOP_TOOLS.has(toolLookupName(call));
}

/** Hands the chat's live browses to the turns that made them. */
export const LiveBrowsesProvider = LiveBrowses.Provider;

/** Browser transcript links and computer previews associated with this turn. */
export function TurnBrowses({ calls }: { calls: ToolCall[] }) {
  const { browses: live, onComment } = useContext(LiveBrowses);
  const visits = turnBrowseVisits(calls, live);
  if (visits.length === 0) return null;
  return (
    <div
      className={cn(
        "grid w-full min-w-0 gap-2 py-1",
        visits.length > 1 ? "md:grid-cols-2" : "max-w-3xl",
      )}
    >
      {visits.map(({ id, call, browse }) =>
        browse ? (
          browse.navigable || browse.nativeId ? (
            <BrowserLink key={id} browse={browse} />
          ) : (
            <InlineBrowser
              key={id}
              browse={browse}
              surface={isDesktop(call) ? "computer" : "browser"}
              onComment={onComment}
            />
          )
        ) : (
          <RecordedBrowse key={id} call={call} />
        ),
      )}
    </div>
  );
}

/** A browse from an earlier turn: where it went, and the way there. */
function RecordedBrowse({ call }: { call: ToolCall }) {
  const t = useTranslations("chat");
  if (!isDesktop(call)) return <BrowserVisit {...recordedBrowserPage(call)} />;
  return (
    <div className="text-muted-foreground flex items-center gap-2 py-1 text-xs">
      <Monitor className="size-4" aria-hidden />
      {t("computerLineUsed")}
    </div>
  );
}

/**
 * One browse as a browser under the message: a fixed-ratio window that grows and
 * shrinks with the conversation, the page laid out at its size.
 *
 * The live socket is this window's while it shows the browse, and is let go while
 * the same browse is open full screen - one view of a tab holds one socket.
 */
function InlineBrowser({
  browse: streamed,
  onComment,
  surface,
}: {
  browse: Browse;
  onComment?: (comment: PageComment) => void;
  surface: BrowseSurface;
}) {
  const t = useTranslations("chat");
  const workspace = useTranslations("chat.workspace");
  const { browses, surfaces = new Map() } = useContext(LiveBrowses);
  const expand = useBrowserPanelStore((state) => state.open);
  const choice = useBrowserPanelStore((state) => state.surface);
  const callId = useBrowserPanelStore((state) => state.openCallId);
  const selected = choice === "files" ? null : choice;
  const expanded =
    selectedWorkspaceBrowse(browses, surfaces, selected, callId)?.callId === streamed.callId;
  const running = isRunning(streamed);
  const live = useLiveBrowse(
    streamed.runId ?? "",
    streamed.callId,
    Boolean(streamed.runId) && !expanded,
  );
  // The live view's copy while the browse runs: it knows who holds the browser
  // and whether this person may, which the conversation's stream does not say.
  const mine = running && live.browse?.callId === streamed.callId;
  const browse = withLivePreview(streamed, live.browse);
  return (
    <div className="border-border bg-background aspect-[16/11] w-full min-w-0 overflow-hidden rounded-2xl border shadow-sm">
      {expanded ? (
        <button
          type="button"
          onClick={() => expand(streamed.callId, surface)}
          className="text-muted-foreground hover:text-foreground flex h-full w-full flex-col items-center justify-center gap-2 text-sm"
        >
          <Maximize2 className="size-5" aria-hidden />
          {surface === "computer"
            ? workspace("openComputer")
            : t("browserShownInPanel", { host: hostOf(browse.url) ?? t("browserHeading") })}
        </button>
      ) : (
        <BrowserWindow
          waitForFit
          browse={browse}
          surface={surface}
          control={
            mine && live.status === "live"
              ? { canControl: live.canControl, canRemember: live.canRemember, send: live.send }
              : null
          }
          maximizeLabel={t("browserOpenPanel")}
          onMaximize={() => expand(streamed.callId, surface)}
          newTabHref={streamed.runId ? `/browse/${streamed.runId}/${streamed.callId}` : undefined}
          onComment={onComment}
        />
      )}
    </div>
  );
}

/** A compact transcript entry that reopens the browser side panel. */
function BrowserLink({ browse }: { browse: Browse }) {
  const open = useBrowserPanelStore((state) => state.open);
  const page = recordedBrowserPage({ args: { url: browse.url }, result: undefined });
  return <BrowserVisit url={page.url} title={browse.title} onOpen={() => open(browse.callId)} />;
}
