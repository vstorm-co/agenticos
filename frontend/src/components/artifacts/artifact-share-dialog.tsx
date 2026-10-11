"use client";

import { useTranslations } from "next-intl";

import { PublicLinkCard } from "@/components/artifacts/public-link-card";
import { EmbedSnippet, PublicLinkSettings } from "@/components/artifacts/public-link-settings";
import { CopyButton } from "@/components/chat/copy-button";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useOrgStore } from "@/stores";
import type { ArtifactDetail, ArtifactPublicLinkUpdate, ArtifactVersion } from "@/types/artifact";

interface ArtifactShareDialogProps {
  artifact: ArtifactDetail;
  /** The kept versions, newest first - what the public link may be pinned to. */
  versions: ArtifactVersion[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A public-link request is in flight. */
  busy: boolean;
  /** Turns the public link on, or replaces the one that is on. */
  onEnablePublicLink: () => void;
  onDisablePublicLink: () => void;
  /** Changes the link's settings; rejects with the server's refusal. */
  onUpdatePublicLink: (changes: ArtifactPublicLinkUpdate) => Promise<unknown>;
  /** A settings change is in flight. */
  saving: boolean;
}

/**
 * The page's own address, for pasting into a message.
 *
 * Inside the dialog's content, which mounts only while it is open, so the origin
 * is read in the browser that shows it and never during a server render. It
 * names the organization as the agent's own link does (`?org=`), which the
 * console adopts on arrival.
 */
function PageLinkField({ artifactId }: { artifactId: string }) {
  const t = useTranslations("artifacts");
  // The organization it was opened in, which is the one it lives in: a reader
  // last working in another would otherwise be told it is not available.
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const org = activeOrgId === null ? "" : `?org=${activeOrgId}`;
  const pageUrl = `${window.location.origin}${ROUTES.ARTIFACT_DETAIL(artifactId)}${org}`;
  return (
    <div className="space-y-2">
      <Label htmlFor="artifact-page-link">{t("pageLink")}</Label>
      <div className="flex items-center gap-2">
        <Input id="artifact-page-link" readOnly value={pageUrl} className="font-mono text-xs" />
        <CopyButton text={pageUrl} className="h-8 w-8 opacity-100" />
      </div>
      <p className="text-muted-foreground text-sm">{t("pageLinkWhy")}</p>
    </div>
  );
}

/**
 * Everything that decides who can open one artifact, in the order people reach for it.
 *
 * The page's own address first: it is what gets pasted into a message, and it
 * opens only for somebody the rules below already let in - so handing it on
 * shares nothing by itself. Then the public link, which is the one way to reach
 * somebody with no account, and then visibility and grants, which are how a
 * member is let in. A reader sees all three and can change none of them.
 */
export function ArtifactShareDialog({
  artifact,
  versions,
  open,
  onOpenChange,
  busy,
  onEnablePublicLink,
  onDisablePublicLink,
  onUpdatePublicLink,
  saving,
}: ArtifactShareDialogProps) {
  const t = useTranslations("artifacts");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("shareTitle", { title: artifact.title })}</DialogTitle>
          <DialogDescription>{t("shareWhy")}</DialogDescription>
        </DialogHeader>
        <PageLinkField artifactId={artifact.id} />
        <PublicLinkCard
          publicUrl={artifact.public_url}
          link={artifact.public_link}
          canManage={artifact.can_edit}
          busy={busy}
          onEnable={onEnablePublicLink}
          onDisable={onDisablePublicLink}
        >
          <EmbedSnippet link={artifact.public_link} />
          {artifact.can_edit && (
            <PublicLinkSettings
              // A fresh form for fresh settings: its fields start from what the server holds.
              key={JSON.stringify(artifact.public_link)}
              link={artifact.public_link}
              versions={versions}
              saving={saving}
              onSave={onUpdatePublicLink}
            />
          )}
        </PublicLinkCard>
        <SharingPanel
          resourceType="artifact"
          resourceId={artifact.id}
          canManage={artifact.can_edit}
        />
      </DialogContent>
    </Dialog>
  );
}
