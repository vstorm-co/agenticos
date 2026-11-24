"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileX } from "lucide-react";
import { useTranslations } from "next-intl";

import { ArtifactRunDialog } from "@/components/artifacts/artifact-run-dialog";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/ui";
import {
  useArtifactActions,
  useAskingGate,
  type AskingGate,
  type PausedRun,
} from "@/hooks/use-artifact-actions";
import { useArtifactData, useArtifactReasons, useArtifactView } from "@/hooks/use-artifacts";
import { useRegisterAssistantPageContext } from "@/hooks/use-assistant-page-context";
import {
  sanitizeAssistantPageDetails,
  type AssistantPageDetails,
} from "@/lib/assistant-page-context";
import { pageOf } from "@/lib/assistant-bubbles";
import { usePathname } from "@/lib/locale-navigation";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { ArtifactTheme } from "@/types/artifact";
import { cn } from "@/lib/utils";
import type {
  AnyBindingData,
  ArtifactActionView,
  ArtifactData,
  BindingData,
  WorkflowLogData,
} from "@/types/artifact";

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

/**
 * Explicit context from the active document, using the data bridge's per-load
 * nonce. The app can describe a view, but cannot claim another resource/title.
 */
export function assistantContextFrom(
  event: MessageEvent,
  frame: HTMLIFrameElement | null,
  nonce: string,
): { details: AssistantPageDetails } | null {
  if (
    !nonce ||
    frame === null ||
    frame.contentWindow === null ||
    event.source !== frame.contentWindow
  ) {
    return null;
  }
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const message = data as { type?: unknown; n?: unknown; context?: unknown };
  if (message.type !== "assistant_context" || message.n !== nonce) return null;
  if (
    message.context !== null &&
    (typeof message.context !== "object" || Array.isArray(message.context))
  )
    return null;
  const {
    title: _title,
    resource: _resource,
    ...details
  } = sanitizeAssistantPageDetails(message.context);
  return { details };
}

/** A binding as the page receives it. */
type PageBinding =
  Omit<BindingData, "reason" | "changed"> | Omit<WorkflowLogData, "reason" | "changed">;

/**
 * The bindings without `reason` and `changed`, which say why a source is
 * unavailable to the editor's strip and are never the page's to show.
 *
 * Names are read only as own keys (`Object.entries`) and written back by
 * `Object.fromEntries`, which defines each one: a binding called `__proto__`
 * stays a key of the answer and never becomes its prototype, whatever publish
 * let through.
 */
function forPage(bindings: Record<string, AnyBindingData>): Record<string, PageBinding> {
  return Object.fromEntries(
    Object.entries(bindings).map(([name, { reason: _reason, changed: _changed, ...binding }]) => [
      name,
      binding,
    ]),
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
  payload: Record<string, AnyBindingData> | undefined,
  dataUpdatedAt: number,
): { subscribes: boolean; onLoad: () => void } {
  const handshake = useRef<Handshake>(freshHandshake(nonce));
  const [said, setSaid] = useState({ nonce, subscribes: false });

  useEffect(() => {
    const current = () => {
      if (handshake.current.nonce !== nonce) handshake.current = freshHandshake(nonce);
      return handshake.current;
    };
    const post = (state: Handshake, bindings: Record<string, AnyBindingData>) => {
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
export function useLinkRequests(
  frame: React.RefObject<HTMLIFrameElement | null>,
  asking: AskingGate,
) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    const listen = (event: MessageEvent) => {
      const href = requestedLink(event, frame.current);
      // Dropped while the console is already asking - about another link or a run.
      if (href !== null && asking.take("link")) setPending(href);
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [frame, asking]);
  const close = useCallback(() => {
    asking.release("link");
    setPending(null);
  }, [asking]);
  return [pending, close] as const;
}

interface ArtifactFrameViewProps {
  /** App preference, independent of the console; authored CSS stays in control. */
  theme?: ArtifactTheme;
  /** A signed content address the server minted for this viewer. */
  url: string;
  title: string;
  /** Replaces the framed card look, for a surface where the page is the whole window. */
  className?: string;
  /**
   * The caller that talks to the page: the frame's element, and each load of it.
   * None on the public link, whose pages are never live.
   */
  bridge?: {
    frame: React.RefObject<HTMLIFrameElement | null>;
    onLoad: () => void;
    /** Shared with the run dialog: one question to the person at a time. */
    asking: AskingGate;
  };
}

/** The page itself, in its sandbox. Shared by the console and the public link. */
export function ArtifactFrameView({
  url,
  title,
  className,
  bridge,
  theme = "light",
}: ArtifactFrameViewProps) {
  const own = useRef<HTMLIFrameElement>(null);
  const frame = bridge?.frame ?? own;
  const ownAsking = useAskingGate();
  const [pending, close] = useLinkRequests(frame, bridge?.asking ?? ownAsking);
  return (
    <>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- `load` is the document finishing, not a person's input; the bridge forgets its handshake on it */}
      <iframe
        ref={frame}
        onLoad={bridge?.onLoad}
        src={url}
        style={{ colorScheme: theme }}
        title={title}
        sandbox={ARTIFACT_SANDBOX}
        referrerPolicy="no-referrer"
        className={cn("h-full min-h-[32rem] w-full rounded-lg border bg-white", className)}
      />
      <LinkRequestDialog pending={pending} onDone={close} />
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
  /**
   * What the address says about the page's data, when it was served with it and so
   * nothing was read here: everyone may know that, unlike why a source is empty.
   */
  served: ServedSummary | null;
}

/** What minting the page's address told, for a strip that has read nothing. */
export interface ServedSummary {
  bindings: number;
  /** The data waits for its owner's consent, so every binding is empty. */
  awaitingConsent: boolean;
}

/** What the frame lends the strip above it. */
export interface DataBridge {
  refresh: () => Promise<void>;
  status: BridgeStatus;
  /** What the page may ask the person to run, for the strip that lists it. */
  actions: ArtifactActionView[];
  /** Runs the page started that now wait on someone. */
  paused: PausedRun[];
}

/** What a view that carries no actions offers: the same list every time. */
const NO_ACTIONS: ArtifactActionView[] = [];

/**
 * What a page gets when its data cannot be read: no bindings, which it fills
 * in as unavailable at once rather than waiting out its own deadline.
 */
const NO_DATA: Record<string, AnyBindingData> = {};

/** The address a framed page asked to open, read by a person before it opens. */
export function LinkRequestDialog({
  pending,
  onDone,
}: {
  pending: string | null;
  onDone: () => void;
}) {
  const t = useTranslations("artifacts");
  return (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) onDone();
      }}
      title={t("openLinkTitle")}
      description={
        <>
          {t("openLinkWhy")}
          <span className="text-foreground mt-2 block font-mono text-xs break-all">{pending}</span>
        </>
      }
      confirmLabel={t("openLink")}
      onConfirm={() => {
        if (pending !== null) window.open(pending, "_blank", "noopener,noreferrer");
        onDone();
      }}
    />
  );
}

interface ArtifactFrameProps {
  theme?: ArtifactTheme;
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
  /**
   * Ask, once the page has loaded, why a source is empty, for a page served with its
   * data: an editor's strip says why, and only the data route tells them. The records
   * are not read again - the page has them.
   */
  fetchReasons?: boolean;
}

/**
 * One version of an artifact, loaded from a freshly signed address.
 *
 * A refusal here comes after the artifact itself was readable, so it means the
 * version was pruned or access was withdrawn a moment ago - both are "this is not
 * available", and neither is worth a retry.
 *
 * A live version's records come with the page when it is served with them
 * (`injected`); otherwise they are read here, as the viewer, and posted to the page
 * when it asks (`useDataBridge`). `refresh` reads them again: a page that listens
 * gets them in place, and one that does not is minted and loaded again once the
 * read is in, so the `ready` of the new load is answered with it. A read that
 * says a newer version was published moves a frame showing the current version
 * onto it (`useArtifactData`).
 *
 * Only here, never in `ArtifactFrameView`, does the console answer a page's
 * request to run an action (`useArtifactActions`): the view is also the public
 * link's, an embed's and a thumbnail's, whose pages are never the viewer's.
 */
export function ArtifactFrame({
  artifactId,
  versionId,
  title,
  className,
  onBridge,
  fetchReasons = false,
  theme,
}: ArtifactFrameProps) {
  const t = useTranslations("artifacts");
  const ts = useTranslations("states");
  const frame = useRef<HTMLIFrameElement>(null);
  const asking = useAskingGate();
  // Only the page the viewer is served is opened with its data; a version picked from
  // the history is a preview of the past and carries none.
  const view = useArtifactView(artifactId, versionId, true, versionId === null);
  const live = view.data?.live === true;
  // A page served with its data already has it: the first load reads nothing here,
  // but for an editor's strip, which asks why once the page has loaded. `refresh`
  // still reads it - `refetch` runs a disabled query - and posts it.
  const injected = view.data?.injected === true;
  const nonce = view.data?.nonce ?? "";
  const pathname = usePathname();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const primaryPage = pageOf(pathname) === `/apps/${artifactId}`;
  const resolvedVersionId = view.data?.version.id ?? "";
  // Identity includes the owning account/organization and document. A reused
  // component must never publish a previous app's view under a new scope.
  const contextIdentity = JSON.stringify([
    userId,
    orgId,
    pathname,
    artifactId,
    resolvedVersionId,
    nonce,
    view.data?.url,
  ]);
  const loadedContextIdentity = useRef<string | null>(null);
  const [appContext, setAppContext] = useState<{
    identity: string;
    details: AssistantPageDetails;
  } | null>(null);
  const currentDetails = appContext?.identity === contextIdentity ? appContext.details : null;
  const assistantDetails = useMemo<AssistantPageDetails>(() => {
    const filters = Object.fromEntries(
      Object.entries(currentDetails?.filters ?? {}).filter(([key]) => key !== "version"),
    );
    return {
      ...currentDetails,
      title,
      resource: { kind: "app", id: artifactId, title },
      view: currentDetails?.view ?? "app",
      // First so the host-owned version survives the bounded filter allowlist.
      filters: { version: resolvedVersionId, ...filters },
    };
  }, [currentDetails, title, artifactId, resolvedVersionId]);
  useEffect(() => {
    if (!primaryPage || !nonce || view.isError) return;
    const listen = (event: MessageEvent) => {
      if (loadedContextIdentity.current !== contextIdentity) return;
      const message = assistantContextFrom(event, frame.current, nonce);
      if (message !== null) {
        setAppContext({ identity: contextIdentity, details: message.details });
      }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [primaryPage, nonce, contextIdentity, view.isError]);
  const onAssistantLoad = useCallback(() => {
    loadedContextIdentity.current = contextIdentity;
    setAppContext(null);
    if (primaryPage && nonce && !view.isError) {
      frame.current?.contentWindow?.postMessage(
        { type: "assistant_context_request", n: nonce },
        "*",
      );
    }
  }, [contextIdentity, primaryPage, nonce, view.isError]);
  const data = useArtifactData(artifactId, view.data?.version.id, live && !injected);
  // After the load, never beside it: the page's own load holds the member's one read in
  // flight until its document is served, and a second would be refused or refuse it.
  const [loadedNonce, setLoadedNonce] = useState<string | null>(null);
  const reasons = useArtifactReasons(
    artifactId,
    view.data?.version.id,
    nonce,
    live && injected && fetchReasons && loadedNonce === nonce,
  );
  // A read cached from before this load was minted - a refresh, then a confirm or a
  // withdrawal that minted again - describes a page nobody sees any more. An injected
  // load already carries its own data, so such a read is neither posted nor shown.
  const fresh =
    !injected || Math.max(data.dataUpdatedAt, data.errorUpdatedAt) >= view.dataUpdatedAt;
  // What the strip is told: the page's own read once it has made one, and until then,
  // for an injected page, why its sources are empty.
  const told = fresh ? data : reasons;
  // A read of a version no longer current, while the frame follows the current
  // one, is never posted: `useArtifactData` has the frame minted onto the newer
  // version, and its page is answered with that version's data.
  const moving = versionId === null && data.data?.current === false;
  const payload = !fresh
    ? undefined
    : data.isError
      ? NO_DATA
      : moving
        ? undefined
        : data.data?.bindings;
  const { subscribes, onLoad } = useDataBridge(frame, nonce, payload, data.dataUpdatedAt);

  const actions = view.data?.actions ?? NO_ACTIONS;
  const run = useArtifactActions({
    artifactId,
    frame,
    nonce,
    versionId: view.data?.version.id ?? "",
    enabled: view.data?.actions_enabled === true,
    actions,
    asking,
  });
  const { onLoad: onRunLoad } = run;
  const loaded = useCallback(() => {
    onLoad();
    onRunLoad();
    onAssistantLoad();
    setLoadedNonce(nonce);
  }, [onLoad, onRunLoad, onAssistantLoad, nonce]);

  const { refetch: refetchData } = data;
  const { refetch: refetchView } = view;
  const refresh = useCallback(async () => {
    // A page that does not listen is loaded again, and the new load carries the
    // data itself: reading it here as well would be a second read for nothing.
    if (live && (subscribes || !injected)) await refetchData();
    if (!subscribes) await refetchView();
  }, [live, injected, subscribes, refetchData, refetchView]);
  const awaitingConsent = view.data?.awaiting_consent === true;
  const bindingCount = view.data?.bindings ?? 0;
  const status = useMemo<BridgeStatus>(
    () => ({
      data: told.data,
      error: told.error,
      // The refresh in flight is the page's own read even while the strip still shows why.
      fetching: data.isFetching || told.isFetching,
      subscribes,
      served: injected ? { bindings: bindingCount, awaitingConsent } : null,
    }),
    [
      told.data,
      told.error,
      told.isFetching,
      data.isFetching,
      subscribes,
      injected,
      bindingCount,
      awaitingConsent,
    ],
  );
  // One object per change of either, and the callback read from a ref: a caller
  // passing an inline `onBridge` that stores the bridge in state would otherwise
  // re-render, hand a new callback, and be called again, forever.
  const { paused } = run;
  const bridge = useMemo<DataBridge>(
    () => ({ refresh, status, actions, paused }),
    [refresh, status, actions, paused],
  );
  const report = useRef(onBridge);
  useEffect(() => {
    report.current = onBridge;
  });
  useEffect(() => {
    report.current?.(bridge);
  }, [bridge]);

  if (view.isLoading)
    return (
      <Skeleton
        role="status"
        aria-label={ts("loading")}
        className={cn("h-full min-h-[32rem] w-full rounded-lg border", className)}
      />
    );
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
    <>
      <AssistantContextRegistration
        key={"assistant-context:" + contextIdentity}
        details={assistantDetails}
        enabled={primaryPage && !view.isError}
      />
      <ArtifactFrameView
        key={contextIdentity}
        url={view.data.url}
        title={title}
        className={className}
        bridge={{ frame, onLoad: loaded, asking }}
        theme={theme}
      />
      <ArtifactRunDialog
        pending={run.pending}
        pageTitle={title}
        onCancel={run.cancel}
        onConfirm={() => void run.confirm()}
      />
    </>
  );
}

/** Remount the registration with the document/account whose data it describes. */
function AssistantContextRegistration({
  details,
  enabled,
}: {
  details: AssistantPageDetails;
  enabled: boolean;
}) {
  useRegisterAssistantPageContext(details, enabled);
  return null;
}
