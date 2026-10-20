"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileX } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState, LoadingState } from "@/components/states";
import { ConfirmDialog } from "@/components/ui";
import { useArtifactData, useArtifactView } from "@/hooks/use-artifacts";
import { cn } from "@/lib/utils";
import type { ArtifactData, BindingData } from "@/types/artifact";

/**
 * What the frame lets the page do. Never `allow-same-origin`, never popups.
 *
 * The response carries the same list as a `sandbox` policy, which is what
 * actually isolates the page - it holds even when somebody opens the content
 * address on its own. The attribute is the second lock on the same door: an
 * agent-authored document runs script in an opaque origin, so it reads no
 * cookie and no storage of this console, and cannot reach the parent frame.
 * No popups because a new window is a navigation, which no `connect-src`
 * governs. A link inside the page asks this frame's parent instead - see
 * `useLinkRequests` - and a person reads the address before anything opens.
 */
export const ARTIFACT_SANDBOX = "allow-scripts allow-modals";

/** What the platform script inside every served page posts when a link is clicked. */
const OPEN_LINK = "agenticos:open-link";

/**
 * The address a message from this frame asks to open, or null for anything else.
 *
 * Only the frame's own window counts - any other frame on the page can post a
 * message too - and only an `http:` or `https:` address: a `javascript:` URL
 * opened from here would run as this console.
 */
export function requestedLink(event: MessageEvent, frame: HTMLIFrameElement | null): string | null {
  if (frame === null || event.source !== frame.contentWindow) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null) return null;
  const { type, href } = data as { type?: unknown; href?: unknown };
  if (type !== OPEN_LINK || typeof href !== "string") return null;
  try {
    const url = new URL(href);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** What the data bridge inside a bound page posts while it waits for its data. */
const READY = "agenticos:ready";

/** What the console posts back: the page's bindings, under the nonce of its load. */
const DATA = "agenticos:data";

/**
 * What a message from this frame says about its page, or null unless it is a
 * `ready` from this load of it.
 *
 * The same source check as `requestedLink`, and the nonce the server minted for
 * this load: a document of the version shown before - still answering as the
 * frame swaps - posts another one.
 */
export function readyFrom(
  event: MessageEvent,
  frame: HTMLIFrameElement | null,
  nonce: string,
): { subscribes: boolean } | null {
  if (frame === null || event.source !== frame.contentWindow) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null) return null;
  const { type, n, subscribes } = data as { type?: unknown; n?: unknown; subscribes?: unknown };
  if (type !== READY || n !== nonce) return null;
  return { subscribes: subscribes === true };
}

/** A binding as the page receives it. */
type PageBinding = Omit<BindingData, "reason">;

/**
 * The bindings without `reason`, which says why a source is unavailable to the
 * editor's strip and is never the page's to show.
 *
 * Names are read only as own keys (`Object.entries`) and written back by
 * `Object.fromEntries`, which defines each one: a binding called `__proto__`
 * stays a key of the answer and never becomes its prototype, whatever publish
 * let through.
 */
function forPage(bindings: Record<string, BindingData>): Record<string, PageBinding> {
  return Object.fromEntries(
    Object.entries(bindings).map(([name, { reason: _reason, ...binding }]) => [name, binding]),
  );
}

/** Where one load of the page stands. */
interface Handshake {
  nonce: string;
  /** The page said `ready` since the frame last loaded. */
  asked: boolean;
  /** What the last `ready` said: it listens, so a new read is posted in place. */
  subscribes: boolean;
  /** The `dataUpdatedAt` of the read last posted, or null before the first post. */
  postedAt: number | null;
}

function freshHandshake(nonce: string): Handshake {
  return { nonce, asked: false, subscribes: false, postedAt: null };
}

/**
 * The console's half of a bound page's data: answers the page's `ready` with
 * what was read for it, and nothing more.
 *
 * - Every load of the frame - and every new nonce - forgets the handshake, so
 *   nothing is posted to a document that has not said `ready` since it loaded.
 * - The first `ready` after that lets one post through: at once when the
 *   payload is in, otherwise when it arrives.
 * - After it, a `ready` only updates `subscribes`, so a page resending costs no
 *   clone; and each completed read - a new `dataUpdatedAt` - is posted once
 *   more, but only to a page whose last `ready` said it listens.
 *
 * It never reads anything itself: the data is the caller's query, fetched as
 * the viewer, and a `ready` is never a reason to fetch. `*` as the target
 * because the page's origin is opaque and cannot be named.
 */
export function useDataBridge(
  frame: React.RefObject<HTMLIFrameElement | null>,
  nonce: string,
  payload: Record<string, BindingData> | undefined,
  dataUpdatedAt: number,
): { subscribes: boolean; onLoad: () => void } {
  const handshake = useRef<Handshake>(freshHandshake(nonce));
  const [said, setSaid] = useState({ nonce, subscribes: false });

  useEffect(() => {
    const current = () => {
      if (handshake.current.nonce !== nonce) handshake.current = freshHandshake(nonce);
      return handshake.current;
    };
    const post = (state: Handshake, bindings: Record<string, BindingData>) => {
      frame.current?.contentWindow?.postMessage(
        { type: DATA, n: nonce, bindings: forPage(bindings) },
        "*",
      );
      state.postedAt = dataUpdatedAt;
    };

    const state = current();
    if (state.asked && payload !== undefined) {
      if (state.postedAt === null || (state.subscribes && state.postedAt !== dataUpdatedAt)) {
        post(state, payload);
      }
    }

    const listen = (event: MessageEvent) => {
      const ready = readyFrom(event, frame.current, nonce);
      if (ready === null) return;
      const latest = current();
      latest.asked = true;
      latest.subscribes = ready.subscribes;
      setSaid((prev) =>
        prev.nonce === nonce && prev.subscribes === ready.subscribes
          ? prev
          : { nonce, subscribes: ready.subscribes },
      );
      if (latest.postedAt === null && payload !== undefined) post(latest, payload);
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [frame, nonce, payload, dataUpdatedAt]);

  const onLoad = useCallback(() => {
    handshake.current = freshHandshake(nonce);
    setSaid({ nonce, subscribes: false });
  }, [nonce]);

  return { subscribes: said.nonce === nonce && said.subscribes, onLoad };
}

/**
 * The first link the framed page asked to open, until somebody decides about it.
 *
 * The first, not the latest: the page may post again while the confirmation is
 * open, and taking the newer address would swap the one the reader is checking
 * for one they never saw, just before they click.
 */
function useLinkRequests(frame: React.RefObject<HTMLIFrameElement | null>) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    const listen = (event: MessageEvent) => {
      const href = requestedLink(event, frame.current);
      if (href !== null) setPending((current) => current ?? href);
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [frame]);
  return [pending, setPending] as const;
}

interface ArtifactFrameViewProps {
  /** A signed content address the server minted for this viewer. */
  url: string;
  title: string;
  /** Replaces the framed card look, for a surface where the page is the whole window. */
  className?: string;
  /**
   * The caller that talks to the page: the frame's element, and each load of it.
   * None on the public link, whose pages are never live.
   */
  bridge?: { frame: React.RefObject<HTMLIFrameElement | null>; onLoad: () => void };
}

/** The page itself, in its sandbox. Shared by the console and the public link. */
export function ArtifactFrameView({ url, title, className, bridge }: ArtifactFrameViewProps) {
  const t = useTranslations("artifacts");
  const own = useRef<HTMLIFrameElement>(null);
  const frame = bridge?.frame ?? own;
  const [pending, setPending] = useLinkRequests(frame);
  return (
    <>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- `load` is the document finishing, not a person's input; the bridge forgets its handshake on it */}
      <iframe
        ref={frame}
        onLoad={bridge?.onLoad}
        src={url}
        title={title}
        sandbox={ARTIFACT_SANDBOX}
        referrerPolicy="no-referrer"
        className={cn("h-full min-h-[32rem] w-full rounded-lg border bg-white", className)}
      />
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title={t("openLinkTitle")}
        description={
          <>
            {t("openLinkWhy")}
            <span className="text-foreground mt-2 block font-mono text-xs break-all">
              {pending}
            </span>
          </>
        }
        confirmLabel={t("openLink")}
        onConfirm={() => {
          if (pending !== null) window.open(pending, "_blank", "noopener,noreferrer");
          setPending(null);
        }}
      />
    </>
  );
}

/** Where a page's live data stands, for the strip that says so. */
export interface BridgeStatus {
  /** The last read that answered, kept through the next one. */
  data: ArtifactData | undefined;
  /** Why the last read failed: a 403 or 404 is the data gone for this viewer. */
  error: Error | null;
  fetching: boolean;
  /** The page listens, so a refresh lands in place rather than reloading it. */
  subscribes: boolean;
}

/** What the frame lends the strip above it. */
export interface DataBridge {
  refresh: () => Promise<void>;
  status: BridgeStatus;
}

/**
 * What a page gets when its data cannot be read: no bindings, which it fills
 * in as unavailable at once rather than waiting out its own deadline.
 */
const NO_DATA: Record<string, BindingData> = {};

interface ArtifactFrameProps {
  artifactId: string;
  /** A kept version to show, or null for the current one. */
  versionId: string | null;
  title: string;
  className?: string;
  /**
   * Called with `refresh` and the data's status whenever either changes - the
   * same object until one does, so a caller may keep it in state.
   */
  onBridge?: (bridge: DataBridge) => void;
}

/**
 * One version of an artifact, loaded from a freshly signed address.
 *
 * A refusal here comes after the artifact itself was readable, so it means the
 * version was pruned or access was withdrawn a moment ago - both are "this is not
 * available", and neither is worth a retry.
 *
 * A live version's records are read here, as the viewer, and posted to the page
 * when it asks (`useDataBridge`). `refresh` reads them again: a page that listens
 * gets them in place, and one that does not is minted and loaded again once the
 * read is in, so the `ready` of the new load is answered with it. A read that
 * says a newer version was published moves a frame showing the current version
 * onto it (`useArtifactData`).
 */
export function ArtifactFrame({
  artifactId,
  versionId,
  title,
  className,
  onBridge,
}: ArtifactFrameProps) {
  const t = useTranslations("artifacts");
  const frame = useRef<HTMLIFrameElement>(null);
  const view = useArtifactView(artifactId, versionId, true);
  const live = view.data?.live === true;
  const data = useArtifactData(artifactId, view.data?.version.id, live);
  // A read of a version no longer current, while the frame follows the current
  // one, is never posted: `useArtifactData` has the frame minted onto the newer
  // version, and its page is answered with that version's data.
  const moving = versionId === null && data.data?.current === false;
  const { subscribes, onLoad } = useDataBridge(
    frame,
    view.data?.nonce ?? "",
    data.isError ? NO_DATA : moving ? undefined : data.data?.bindings,
    data.dataUpdatedAt,
  );

  const { refetch: refetchData } = data;
  const { refetch: refetchView } = view;
  const refresh = useCallback(async () => {
    if (live) await refetchData();
    if (!subscribes) await refetchView();
  }, [live, subscribes, refetchData, refetchView]);
  const status = useMemo<BridgeStatus>(
    () => ({ data: data.data, error: data.error, fetching: data.isFetching, subscribes }),
    [data.data, data.error, data.isFetching, subscribes],
  );
  // One object per change of either, and the callback read from a ref: a caller
  // passing an inline `onBridge` that stores the bridge in state would otherwise
  // re-render, hand a new callback, and be called again, forever.
  const bridge = useMemo<DataBridge>(() => ({ refresh, status }), [refresh, status]);
  const report = useRef(onBridge);
  useEffect(() => {
    report.current = onBridge;
  });
  useEffect(() => {
    report.current?.(bridge);
  }, [bridge]);

  if (view.isLoading) return <LoadingState variant="skeleton-panel" rows={4} />;
  if (view.data === undefined) {
    return (
      <EmptyState
        icon={FileX}
        title={t("versionUnavailable")}
        description={t("versionUnavailableWhy")}
      />
    );
  }
  return (
    <ArtifactFrameView
      url={view.data.url}
      title={title}
      className={className}
      bridge={{ frame, onLoad }}
    />
  );
}
