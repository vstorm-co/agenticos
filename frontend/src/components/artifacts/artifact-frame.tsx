"use client";

import { useEffect, useRef, useState } from "react";
import { FileX } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState, LoadingState } from "@/components/states";
import { ConfirmDialog } from "@/components/ui";
import { useArtifactView } from "@/hooks/use-artifacts";
import { cn } from "@/lib/utils";

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

/** The link the framed page last asked to open, until somebody decides about it. */
function useLinkRequests(frame: React.RefObject<HTMLIFrameElement | null>) {
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    const listen = (event: MessageEvent) => {
      const href = requestedLink(event, frame.current);
      if (href !== null) setPending(href);
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
}

/** The page itself, in its sandbox. Shared by the console and the public link. */
export function ArtifactFrameView({ url, title, className }: ArtifactFrameViewProps) {
  const t = useTranslations("artifacts");
  const frame = useRef<HTMLIFrameElement>(null);
  const [pending, setPending] = useLinkRequests(frame);
  return (
    <>
      <iframe
        ref={frame}
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

interface ArtifactFrameProps {
  artifactId: string;
  /** A kept version to show, or null for the current one. */
  versionId: string | null;
  title: string;
  className?: string;
}

/**
 * One version of an artifact, loaded from a freshly signed address.
 *
 * A refusal here comes after the artifact itself was readable, so it means the
 * version was pruned or access was withdrawn a moment ago - both are "this is not
 * available", and neither is worth a retry.
 */
export function ArtifactFrame({ artifactId, versionId, title, className }: ArtifactFrameProps) {
  const t = useTranslations("artifacts");
  const view = useArtifactView(artifactId, versionId, true);

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
  return <ArtifactFrameView url={view.data.url} title={title} className={className} />;
}
