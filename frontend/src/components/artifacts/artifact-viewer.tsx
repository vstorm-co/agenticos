"use client";

import { useState } from "react";
import { FileX, History } from "lucide-react";
import { useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

import { ArtifactFrame } from "@/components/artifacts/artifact-frame";
import { OtherOrganizations } from "@/components/artifacts/other-organizations";
import { ArtifactShareDialog } from "@/components/artifacts/artifact-share-dialog";
import { ArtifactViewerBar } from "@/components/artifacts/artifact-viewer-bar";
import { VersionPicker } from "@/components/artifacts/version-picker";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, ConfirmDialog } from "@/components/ui";
import { useArtifact } from "@/hooks/use-artifacts";
import { ApiError } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

/**
 * One box for the strip and the page, so nothing the layout spaces its children
 * with - the maintenance gate's gap - opens a band between them.
 */
const VIEWER = "flex min-h-0 flex-1 flex-col";

interface ArtifactViewerProps {
  artifactId: string;
  /** The version a link asked for; null opens the current one. */
  initialVersionId: string | null;
}

/**
 * One artifact as its own page: the whole window, under a single strip of console.
 *
 * It opens the way the public link does - the page and nothing around it - but
 * only for somebody signed in whom the artifact's rules let in, and who reaches
 * it is changed from the strip rather than from panels beside the page. Every
 * control that changes it is rendered only when the server said the caller may
 * (`can_edit`, which counts a grant on this artifact as well as the role), so a
 * reader can see who else reaches it and has nothing to press.
 */
export function ArtifactViewer({ artifactId, initialVersionId }: ArtifactViewerProps) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  const router = useRouter();
  const [versionId, setVersionId] = useState(initialVersionId);
  const [sharing, setSharing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const {
    artifact,
    versions,
    isLoading,
    error,
    refetch,
    enablePublicLink,
    disablePublicLink,
    updatePublicLink,
    restoreVersion,
    remove,
  } = useArtifact(artifactId);

  if (artifact === null) {
    // The two do not read the same. A 404 is a fact about the artifact - gone,
    // in another tenant or no longer shared, which the API answers identically on
    // purpose. Anything else is a fact about the request, and telling somebody
    // their page was removed during an outage sends them to ask who deleted it.
    const unavailable = !error || (error instanceof ApiError && error.status === 404);
    return (
      <div className={VIEWER}>
        <ArtifactViewerBar artifact={null} />
        <div className="flex flex-1 items-center justify-center p-6">
          {isLoading ? (
            <LoadingState variant="skeleton-panel" rows={6} />
          ) : unavailable ? (
            <div className="flex flex-col items-center gap-4">
              <EmptyState icon={FileX} title={t("unavailable")} description={t("unavailableWhy")} />
              <OtherOrganizations />
            </div>
          ) : (
            <ErrorState
              title={t("couldNotLoad")}
              cta={{ label: tc("retry"), onClick: () => void refetch() }}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={VIEWER}>
      <ArtifactViewerBar
        artifact={artifact}
        onShare={() => setSharing(true)}
        onDelete={() => setConfirming(true)}
      >
        <VersionPicker versions={versions} value={versionId} onChange={setVersionId} />
        {artifact.can_edit && versionId !== null && versionId !== artifact.current_version?.id && (
          <Button
            size="sm"
            variant="outline"
            disabled={restoreVersion.isPending}
            onClick={() =>
              restoreVersion.mutate(versionId, { onSuccess: () => setVersionId(null) })
            }
          >
            <History className="h-3.5 w-3.5" />
            <span className="sr-only sm:not-sr-only">{t("restoreVersion")}</span>
          </Button>
        )}
      </ArtifactViewerBar>
      <div className="flex min-h-0 flex-1 flex-col">
        <ArtifactFrame
          artifactId={artifact.id}
          versionId={versionId}
          title={artifact.title}
          className="min-h-0 rounded-none border-0"
        />
      </div>
      <ArtifactShareDialog
        artifact={artifact}
        open={sharing}
        onOpenChange={setSharing}
        versions={versions}
        busy={enablePublicLink.isPending || disablePublicLink.isPending}
        onEnablePublicLink={() => enablePublicLink.mutate()}
        onDisablePublicLink={() => disablePublicLink.mutate()}
        onUpdatePublicLink={(changes) => updatePublicLink.mutateAsync(changes)}
        saving={updatePublicLink.isPending}
      />
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("deleteTitle", { title: artifact.title })}
        description={t("deleteWhy")}
        confirmLabel={tc("delete")}
        destructive
        loading={remove.isPending}
        onConfirm={async () => {
          await remove.mutateAsync();
          router.push(ROUTES.ARTIFACTS);
        }}
      />
    </div>
  );
}
