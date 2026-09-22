"use client";

import { FileX } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState, LoadingState } from "@/components/states";
import { useArtifactView } from "@/hooks/use-artifacts";

/**
 * What the frame lets the page do. Never `allow-same-origin`.
 *
 * The response carries the same list as a `sandbox` policy, which is what
 * actually isolates the page - it holds even when somebody opens the content
 * address on its own. The attribute is the second lock on the same door: an
 * agent-authored document runs script in an opaque origin, so it reads no
 * cookie and no storage of this console, and cannot reach the parent frame.
 */
export const ARTIFACT_SANDBOX =
  "allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals";

interface ArtifactFrameViewProps {
  /** A signed content address the server minted for this viewer. */
  url: string;
  title: string;
}

/** The page itself, in its sandbox. Shared by the console and the public link. */
export function ArtifactFrameView({ url, title }: ArtifactFrameViewProps) {
  return (
    <iframe
      src={url}
      title={title}
      sandbox={ARTIFACT_SANDBOX}
      referrerPolicy="no-referrer"
      className="h-full min-h-[32rem] w-full rounded-lg border bg-white"
    />
  );
}

interface ArtifactFrameProps {
  artifactId: string;
  /** A kept version to show, or null for the current one. */
  versionId: string | null;
  title: string;
}

/**
 * One version of an artifact, loaded from a freshly signed address.
 *
 * A refusal here comes after the artifact itself was readable, so it means the
 * version was pruned or access was withdrawn a moment ago - both are "this is not
 * available", and neither is worth a retry.
 */
export function ArtifactFrame({ artifactId, versionId, title }: ArtifactFrameProps) {
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
  return <ArtifactFrameView url={view.data.url} title={title} />;
}
