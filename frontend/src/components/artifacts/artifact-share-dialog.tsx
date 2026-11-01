"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ArtifactRequests } from "@/components/artifacts/artifact-requests";
import { ConfirmDataDialog } from "@/components/artifacts/confirm-data-dialog";

import { AutoConsentSetting } from "@/components/artifacts/auto-consent-setting";
import { PublicDataControl } from "@/components/artifacts/public-data-control";
import { PublicLinkCard } from "@/components/artifacts/public-link-card";
import { EmbedSnippet, PublicLinkSettings } from "@/components/artifacts/public-link-settings";
import { CopyButton } from "@/components/chat/copy-button";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import {
  Alert,
  AlertDescription,
  Button,
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
import type {
  ArtifactDetail,
  ArtifactPublicLinkUpdate,
  ArtifactShareRequest,
  ArtifactVersion,
} from "@/types/artifact";

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
  /** Turns auto-consent on or off; see `AutoConsentSetting`. */
  onAutoConsent: (changes: { enabled: boolean; confirmed?: string }, onDone?: () => void) => void;
  savingAutoConsent: boolean;
  /** Opens the review of a version request, over the page rather than in this dialog. */
  onReview: (request: ArtifactShareRequest) => void;
  /** Confirms the latest version's data with the fingerprint shown; rejects with the refusal. */
  onConfirmData: (fingerprint: string) => Promise<unknown>;
  confirmingData: boolean;
  /** Confirms the data for the public link with the digests shown; rejects with the refusal. */
  onConfirmPublicData: (fingerprint: string, audienceDigest: string) => Promise<unknown>;
  confirmingPublicData: boolean;
  onWithdrawPublicData: (onDone: () => void) => void;
  withdrawingPublicData: boolean;
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
  onAutoConsent,
  savingAutoConsent,
  onReview,
  onConfirmData,
  confirmingData,
  onConfirmPublicData,
  confirmingPublicData,
  onWithdrawPublicData,
  withdrawingPublicData,
}: ArtifactShareDialogProps) {
  const t = useTranslations("artifacts");
  // Sharing was refused for want of consent: say so, with the way to give it.
  const [needsConsent, setNeedsConsent] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const confirmable = artifact.consent?.may_confirm === true && artifact.current_version !== null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("shareTitle", { title: artifact.title })}</DialogTitle>
          <DialogDescription>{t("shareWhy")}</DialogDescription>
        </DialogHeader>
        <ArtifactRequests
          artifact={artifact}
          onReview={(request) => {
            onOpenChange(false);
            onReview(request);
          }}
          onConsentRequired={() => setNeedsConsent(true)}
        />
        {needsConsent && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center gap-3">
              <span>
                {confirmable ? t("requests.consentRequired") : t("requests.consentRequiredOwner")}
              </span>
              {confirmable && (
                <Button size="sm" onClick={() => setConfirming(true)}>
                  {t("requests.confirmData")}
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
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
              publicDataConfirmed={artifact.public_data?.consented === true}
              versions={versions}
              saving={saving}
              onSave={onUpdatePublicLink}
            />
          )}
          <PublicDataControl
            artifact={artifact}
            onConfirm={onConfirmPublicData}
            confirmPending={confirmingPublicData}
            onWithdraw={onWithdrawPublicData}
            withdrawPending={withdrawingPublicData}
          />
        </PublicLinkCard>
        <SharingPanel
          resourceType="artifact"
          resourceId={artifact.id}
          canManage={artifact.can_edit}
          mayGrantEditData={artifact.may_grant_edit_data}
          onConsentRequired={() => setNeedsConsent(true)}
        />
        {artifact.consent !== null && (
          <AutoConsentSetting
            consent={artifact.consent}
            onChange={onAutoConsent}
            saving={savingAutoConsent}
          />
        )}
        {confirmable && artifact.current_version !== null && (
          <ConfirmDataDialog
            artifactId={artifact.id}
            versionId={artifact.current_version.id}
            open={confirming}
            onOpenChange={setConfirming}
            onConfirm={async (fingerprint) => {
              await onConfirmData(fingerprint);
              setNeedsConsent(false);
            }}
            loading={confirmingData}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
