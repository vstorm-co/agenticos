"use client";

import { useEffect, useState } from "react";
import { FileX, History, Info } from "lucide-react";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

import {
  ArchiveArtifactDialog,
  ArchivedArtifactNotice,
  DeleteArtifactDialog,
} from "@/components/artifacts/artifact-archive";
import { ArtifactFrame, type DataBridge } from "@/components/artifacts/artifact-frame";
import {
  liveHealth,
  LiveDataNotice,
  LiveRefreshButton,
  ViewerNotice,
} from "@/components/artifacts/live-data-controls";
import { OtherOrganizations } from "@/components/artifacts/other-organizations";
import { ArtifactShareDialog } from "@/components/artifacts/artifact-share-dialog";
import { ArtifactViewerBar } from "@/components/artifacts/artifact-viewer-bar";
import { VersionPicker } from "@/components/artifacts/version-picker";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
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
  const pathname = usePathname();
  const [versionId, setVersionId] = useState(initialVersionId);
  const [sharing, setSharing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [bridge, setBridge] = useState<DataBridge | null>(null);
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
    archive,
    unarchive,
    remove,
  } = useArtifact(artifactId);

  // A link to the version that is current - a chat card names the version its run
  // published - opens the current one, so the page follows what is published next
  // instead of staying on that version once it is replaced. Adjusted while
  // rendering, as React does state that follows other state.
  const currentId = artifact?.current_version?.id;
  if (versionId !== null && versionId === currentId) setVersionId(null);

  // The address says which version is on screen, so a reload opens it again: the
  // version picker, Open current, a restore and a link all land here. No
  // `version` in the address is the current one.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if ((params.get("version") ?? null) === versionId) return;
    if (versionId === null) params.delete("version");
    else params.set("version", versionId);
    const query = params.toString();
    router.replace(query === "" ? pathname : `${pathname}?${query}`, { scroll: false });
  }, [versionId, pathname, router]);

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

  const deleteDialog = (
    <DeleteArtifactDialog
      open={confirming}
      onOpenChange={setConfirming}
      title={artifact.title}
      loading={remove.isPending}
      onConfirm={async () => {
        await remove.mutateAsync();
        router.push(ROUTES.ARTIFACTS);
      }}
    />
  );

  // The server shows an archived page only to somebody who may edit it, so what
  // is left of it here is when it was archived, the way back, and Delete.
  if (artifact.archived_at !== null) {
    return (
      <div className={VIEWER}>
        <ArtifactViewerBar artifact={artifact} onDelete={() => setConfirming(true)} />
        <div className="flex flex-1 items-center justify-center p-6">
          <ArchivedArtifactNotice
            archivedAt={artifact.archived_at}
            restoring={unarchive.isPending}
            onRestore={() => unarchive.mutate()}
          />
        </div>
        {deleteDialog}
      </div>
    );
  }

  // Only the current version reads live data, so only it refreshes; an older
  // one of a live page says so, and offers the current one back.
  const current = versionId === null || versionId === artifact.current_version?.id;
  const live = artifact.live && current;
  const restore = artifact.can_edit && !current && (
    <Button
      size="sm"
      variant="outline"
      disabled={restoreVersion.isPending}
      onClick={() => restoreVersion.mutate(versionId, { onSuccess: () => setVersionId(null) })}
    >
      <History className="h-3.5 w-3.5" />
      <span className="sr-only sm:not-sr-only">{t("restoreVersion")}</span>
    </Button>
  );

  return (
    <div className={VIEWER}>
      <ArtifactViewerBar
        artifact={artifact}
        live={
          live ? (bridge === null ? "steady" : (liveHealth(bridge.status) ?? undefined)) : undefined
        }
        onShare={() => setSharing(true)}
        onArchive={() => setArchiving(true)}
        onDelete={() => setConfirming(true)}
      >
        {live && bridge !== null && (
          <LiveRefreshButton key={artifact.id} artifactId={artifact.id} bridge={bridge} />
        )}
        <VersionPicker
          versions={versions}
          value={versionId}
          onChange={setVersionId}
          live={artifact.live}
        />
        {!artifact.live && restore}
      </ArtifactViewerBar>
      {live && bridge !== null && <LiveDataNotice artifact={artifact} status={bridge.status} />}
      {artifact.live && !current && (
        <ViewerNotice tone="info" icon={Info}>
          <span>{t("liveOnlyCurrent")}</span>
          <Button size="sm" variant="outline" onClick={() => setVersionId(null)}>
            {t("openCurrent")}
          </Button>
          {restore}
        </ViewerNotice>
      )}
      <div className="flex min-h-0 flex-1 flex-col">
        <ArtifactFrame
          artifactId={artifact.id}
          versionId={versionId}
          title={artifact.title}
          className="min-h-0 rounded-none border-0"
          onBridge={setBridge}
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
      <ArchiveArtifactDialog
        open={archiving}
        onOpenChange={setArchiving}
        title={artifact.title}
        loading={archive.isPending}
        onConfirm={() => archive.mutate(undefined, { onSuccess: () => setArchiving(false) })}
      />
      {deleteDialog}
    </div>
  );
}
