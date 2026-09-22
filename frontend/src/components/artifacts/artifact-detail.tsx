"use client";

import { useState } from "react";
import { FileX, Trash2 } from "lucide-react";
import { useRouter } from "@/lib/locale-navigation";
import { useTranslations } from "next-intl";

import { ArtifactFrame } from "@/components/artifacts/artifact-frame";
import { PublicLinkCard } from "@/components/artifacts/public-link-card";
import { VersionPicker } from "@/components/artifacts/version-picker";
import { PageHeader } from "@/components/dashboard/page-header";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { EmptyState, LoadingState } from "@/components/states";
import { Button, ConfirmDialog } from "@/components/ui";
import { useArtifact } from "@/hooks/use-artifacts";
import { ROUTES } from "@/lib/constants";

interface ArtifactDetailProps {
  artifactId: string;
  /** The version a link asked for; null opens the current one. */
  initialVersionId: string | null;
}

/**
 * The page, its versions, its public link and its sharing, for one artifact.
 *
 * Every control that changes it is rendered only when the server said the
 * caller may (`can_edit`, which counts a grant on this artifact as well as the
 * role), so a reader sees the page and who else can, and nothing to press.
 */
export function ArtifactDetail({ artifactId, initialVersionId }: ArtifactDetailProps) {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  const router = useRouter();
  const [versionId, setVersionId] = useState(initialVersionId);
  const [confirming, setConfirming] = useState(false);
  const { artifact, versions, isLoading, enablePublicLink, disablePublicLink, remove } =
    useArtifact(artifactId);
  const breadcrumbs = [{ label: t("title"), href: ROUTES.ARTIFACTS }];

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={6} />;
  if (artifact === null) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("title")} breadcrumbs={breadcrumbs} />
        <EmptyState icon={FileX} title={t("unavailable")} description={t("unavailableWhy")} />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        title={artifact.title}
        description={t("publishedAs", { name: artifact.name })}
        breadcrumbs={[...breadcrumbs, { label: artifact.title }]}
        actions={
          <div className="flex items-center gap-2">
            <VersionPicker versions={versions} value={versionId} onChange={setVersionId} />
            {artifact.can_edit && (
              <Button variant="outline" onClick={() => setConfirming(true)}>
                <Trash2 className="h-4 w-4" />
                {tc("delete")}
              </Button>
            )}
          </div>
        }
      />
      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div data-tour="artifact-frame" className="flex min-h-0 flex-col">
          <ArtifactFrame artifactId={artifact.id} versionId={versionId} title={artifact.title} />
        </div>
        <div className="space-y-6">
          <PublicLinkCard
            publicUrl={artifact.public_url}
            canManage={artifact.can_edit}
            busy={enablePublicLink.isPending || disablePublicLink.isPending}
            onEnable={() => enablePublicLink.mutate()}
            onDisable={() => disablePublicLink.mutate()}
          />
          <SharingPanel
            resourceType="artifact"
            resourceId={artifact.id}
            canManage={artifact.can_edit}
          />
        </div>
      </div>
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
