"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, FileClock, FileX, GitPullRequest, History, Info } from "lucide-react";
import { usePathname, useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

import {
  ArchiveArtifactDialog,
  ArchivedArtifactNotice,
  DeleteArtifactDialog,
} from "@/components/artifacts/artifact-archive";
import { ArtifactFrame, type DataBridge } from "@/components/artifacts/artifact-frame";
import { PausedRuns } from "@/components/artifacts/artifact-run-dialog";
import { ChangeOwnerDialog } from "@/components/artifacts/change-owner-dialog";
import { DataChangeReview } from "@/components/artifacts/data-change-review";
import { RequestAccessScreen } from "@/components/artifacts/request-access-screen";
import { PublicDataNotice } from "@/components/artifacts/public-data-control";
import { ConsentControls } from "@/components/artifacts/consent-controls";
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
import { useArtifactRequestActions, useArtifactRequests } from "@/hooks/use-artifact-requests";
import { useArtifact } from "@/hooks/use-artifacts";
import { ApiError } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores/auth-store";
import type { ArtifactShareRequest } from "@/types/artifact";

/**
 * One box for the strip and the page, so nothing the layout spaces its children
 * with - the maintenance gate's gap - opens a band between them.
 */
const VIEWER = "flex min-h-0 flex-1 flex-col";

interface ArtifactViewerProps {
  artifactId: string;
  /** The version a link asked for; null opens the current one. */
  initialVersionId: string | null;
  /** A link to a request - a notification's - opens the Share dialog on its Requests. */
  openRequests?: boolean;
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
export function ArtifactViewer({
  artifactId,
  initialVersionId,
  openRequests = false,
}: ArtifactViewerProps) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  const router = useRouter();
  const pathname = usePathname();
  const [versionId, setVersionId] = useState(initialVersionId);
  const [sharing, setSharing] = useState(false);
  const [openingRequests, setOpeningRequests] = useState(openRequests);
  const [reviewing, setReviewing] = useState<ArtifactShareRequest | null>(null);
  const [audienceShown, setAudienceShown] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [changingOwner, setChangingOwner] = useState(false);
  const [bridge, setBridge] = useState<DataBridge | null>(null);
  const userId = useAuthStore((state) => state.user?.id ?? null);
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
    follow,
    remove,
    confirmData,
    withdrawConsent,
    confirmPublicData,
    withdrawPublicData,
    setAutoConsent,
    changeOwner,
  } = useArtifact(artifactId);
  // Whoever may decide requests is told what waits on them, in the strip and under it.
  const decider = artifact !== null && (artifact.can_edit || artifact.may_change_owner);
  const { requests } = useArtifactRequests(
    artifactId,
    false,
    decider && artifact.archived_at === null,
  );
  const { decline } = useArtifactRequestActions(artifactId);
  const waiting = requests.filter((request) => request.status === "pending" && request.can_decide);
  const versionRequest = waiting.find((request) => request.kind === "version") ?? null;

  // A link to the version that is current - a chat card names the version its run
  // published - opens the current one, so the page follows what is published next
  // instead of staying on that version once it is replaced. Adjusted while
  // rendering, as React does state that follows other state.
  const currentId = artifact?.current_version?.id;
  if (versionId !== null && versionId === currentId) setVersionId(null);

  // A link to the requests opens the Share dialog once, when the page is there to
  // share; an archived one serves nobody, so it stays shut.
  if (openingRequests && artifact !== null) {
    setOpeningRequests(false);
    if (artifact.archived_at === null) setSharing(true);
  }

  // A request decided elsewhere meanwhile is no longer the one under review.
  if (reviewing !== null && !waiting.some((request) => request.id === reviewing.id)) {
    setReviewing(null);
    if (audienceShown) {
      setAudienceShown(false);
      setVersionId(null);
    }
  }

  // The address says which version is on screen, so a reload opens it again: the
  // version picker, Open current, a restore and a link all land here. No
  // `version` in the address is the current one.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // The link that opened the Requests has done its work: the address no longer asks for it.
    const spent = !openingRequests && params.has("requests");
    if ((params.get("version") ?? null) === versionId && !spent) return;
    params.delete("requests");
    if (versionId === null) params.delete("version");
    else params.set("version", versionId);
    const query = params.toString();
    router.replace(query === "" ? pathname : `${pathname}?${query}`, { scroll: false });
  }, [versionId, openingRequests, pathname, router]);

  if (artifact === null) {
    // The two do not read the same. A 404 is a fact about the artifact - gone,
    // in another tenant or no longer shared, which the API answers identically on
    // purpose. Anything else is a fact about the request, and telling somebody
    // their page was removed during an outage sends them to ask who deleted it.
    const unavailable = !error || (error instanceof ApiError && error.status === 404);
    // A member who may ask for access is told that, and nothing about the page.
    const requestable =
      error instanceof ApiError && error.status === 403 && error.code === "ACCESS_REQUESTABLE"
        ? error
        : null;
    return (
      <div className={VIEWER}>
        <ArtifactViewerBar artifact={null} />
        <div className="flex flex-1 items-center justify-center p-6">
          {isLoading ? (
            <LoadingState variant="skeleton-panel" rows={6} />
          ) : requestable !== null ? (
            <RequestAccessScreen
              artifactId={artifactId}
              requested={requestable.details?.requested === true}
            />
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

  // Nothing of the page is the caller's to open yet: every version reads data its
  // owner has not confirmed sharing, and the caller is only its audience.
  if (artifact.current_version === null) {
    return (
      <div className={VIEWER}>
        <ArtifactViewerBar artifact={null} />
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={FileClock}
            title={t("consent.notAvailableYet")}
            description={t("consent.notAvailableYetWhy")}
          />
        </div>
      </div>
    );
  }

  const served = artifact.current_version;
  const reviewVersionId = reviewing?.version_id ?? null;
  // Closing the review puts the frame back where it was, off the audience's version.
  function closeReview() {
    setReviewing(null);
    if (audienceShown) {
      setAudienceShown(false);
      setVersionId(null);
    }
  }
  // Only the current version reads live data, so only it refreshes; an older
  // one of a live page says so, and offers the current one back.
  const current = versionId === null || versionId === served.id;
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
        actions={bridge?.actions}
        onShare={() => setSharing(true)}
        onArchive={() => setArchiving(true)}
        onDelete={() => setConfirming(true)}
        onWithdrawConsent={() => setWithdrawing(true)}
        onChangeOwner={() => setChangingOwner(true)}
        waitingRequests={waiting.length}
        onRequests={() => setSharing(true)}
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
        <Button
          size="sm"
          variant="outline"
          aria-pressed={artifact.following}
          disabled={follow.isPending}
          onClick={() => follow.mutate(!artifact.following)}
        >
          {artifact.following ? (
            <BellOff className="h-3.5 w-3.5" />
          ) : (
            <Bell className="h-3.5 w-3.5" />
          )}
          <span className="sr-only sm:not-sr-only">
            {artifact.following ? t("unfollow") : t("follow")}
          </span>
        </Button>
        {!artifact.live && restore}
      </ArtifactViewerBar>
      {artifact.consent !== null && (
        <ConsentControls
          artifactId={artifact.id}
          versionId={served.id}
          consent={artifact.consent}
          isOwner={userId !== null && userId === artifact.owner_user_id}
          showNotice={current}
          reviewPending={
            versionRequest !== null && versionRequest.version_number === artifact.consent.version
          }
          withdrawing={withdrawing}
          onWithdrawingChange={setWithdrawing}
          onConfirm={(fingerprint) =>
            confirmData.mutateAsync({ versionId: served.id, fingerprint })
          }
          confirmPending={confirmData.isPending}
          onWithdraw={(onDone) => withdrawConsent.mutate(undefined, { onSuccess: onDone })}
          withdrawPending={withdrawConsent.isPending}
        />
      )}
      <PublicDataNotice
        artifact={artifact}
        onConfirm={(fingerprint, audience_digest) =>
          confirmPublicData.mutateAsync({ fingerprint, audience_digest })
        }
        confirmPending={confirmPublicData.isPending}
      />
      {reviewing !== null && reviewVersionId !== null ? (
        <DataChangeReview
          artifactId={artifact.id}
          versionId={reviewVersionId}
          fingerprint={reviewing.query_fingerprint}
          audienceShown={audienceShown}
          onAudienceShown={(shown, number) => {
            setAudienceShown(shown);
            setVersionId(
              shown ? (versions.find((version) => version.number === number)?.id ?? null) : null,
            );
          }}
          audienceAvailable={(number) => versions.some((version) => version.number === number)}
          onApprove={(fingerprint) =>
            confirmData.mutateAsync({ versionId: reviewVersionId, fingerprint })
          }
          onDecline={() => decline.mutate(reviewing.id, { onSuccess: closeReview })}
          onClose={closeReview}
          pending={confirmData.isPending || decline.isPending}
        />
      ) : (
        versionRequest !== null && (
          <ViewerNotice tone="warning" icon={GitPullRequest} tour="artifact-review">
            <span>
              {t("requests.versionNotice", {
                name: versionRequest.requester_name ?? t("requests.someone"),
                version: versionRequest.version_number ?? 0,
              })}
            </span>
            <Button size="sm" variant="outline" onClick={() => setReviewing(versionRequest)}>
              {t("requests.review")}
            </Button>
          </ViewerNotice>
        )
      )}
      {live && bridge !== null && <LiveDataNotice artifact={artifact} status={bridge.status} />}
      {bridge !== null && <PausedRuns runs={bridge.paused} />}
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
          fetchReasons={artifact.can_edit}
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
        onAutoConsent={(changes, onDone) => setAutoConsent.mutate(changes, { onSuccess: onDone })}
        savingAutoConsent={setAutoConsent.isPending}
        onReview={setReviewing}
        onConfirmData={(fingerprint) =>
          confirmData.mutateAsync({ versionId: served.id, fingerprint })
        }
        confirmingData={confirmData.isPending}
        onConfirmPublicData={(fingerprint, audience_digest) =>
          confirmPublicData.mutateAsync({ fingerprint, audience_digest })
        }
        confirmingPublicData={confirmPublicData.isPending}
        onWithdrawPublicData={(onDone) =>
          withdrawPublicData.mutate(undefined, { onSuccess: onDone })
        }
        withdrawingPublicData={withdrawPublicData.isPending}
      />
      {artifact.may_change_owner && (
        <ChangeOwnerDialog
          artifact={artifact}
          open={changingOwner}
          onOpenChange={setChangingOwner}
          onChangeOwner={(userId, onDone) => changeOwner.mutate(userId, { onSuccess: onDone })}
          pending={changeOwner.isPending}
        />
      )}
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
