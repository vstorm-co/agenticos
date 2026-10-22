"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ConsentQueries } from "@/components/artifacts/consent-disclosure";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Alert,
  AlertDescription,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { usePublicDataDisclosure } from "@/hooks/use-artifacts";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { ArtifactPublicDataDisclosure } from "@/types/artifact";

interface PublicDataDialogProps {
  artifactId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Sends what the person was shown; rejects with the server's refusal. */
  onConfirm: (fingerprint: string, audienceDigest: string) => Promise<unknown>;
  loading: boolean;
}

/** Who the public link reaches: anyone with it, behind its password, until its expiry, and on each site. */
function PublicAudience({ shown }: { shown: ArtifactPublicDataDisclosure }) {
  const t = useTranslations("artifacts.publicData");
  const format = useFormatter();
  return (
    <div className="space-y-1">
      <p className="font-medium">{t("audienceTitle")}</p>
      <ul className="text-muted-foreground list-disc space-y-0.5 pl-5">
        <li>{t("audienceAnyone")}</li>
        <li>{shown.password_protected ? t("audiencePassword") : t("audienceNoPassword")}</li>
        <li>
          {shown.expires_at === null
            ? t("audienceNoExpiry")
            : t("audienceExpires", {
                date: format.dateTime(new Date(shown.expires_at), { dateStyle: "medium" }),
              })}
        </li>
        {shown.embed_origins.length > 0 && (
          <li>{t("audienceEmbeds", { sites: shown.embed_origins.join(", ") })}</li>
        )}
      </ul>
    </div>
  );
}

/**
 * "Confirm data for the public link": the page queries the link serves, then who
 * reaches them - anyone with the link, its password, expiry and embedding sites -
 * and the confirmation, which sends back the digests of exactly what was shown. A
 * page republished, or an embed site added, in between is refused rather than
 * confirmed unseen: a 409 reads the page again and closes the dialog, as the
 * members' dialog does. Any other refusal is shown here and holds the button.
 */
export function PublicDataDialog({
  artifactId,
  open,
  onOpenChange,
  onConfirm,
  loading,
}: PublicDataDialogProps) {
  const t = useTranslations("artifacts.publicData");
  const tErrors = useTranslations("errors");
  const [refusal, setRefusal] = useState<string | null>(null);
  const disclosure = usePublicDataDisclosure(artifactId, open);
  const shown = disclosure.data;
  // The two the console can say in the person's language, else the server's own reason.
  const blocked =
    shown === undefined
      ? null
      : !shown.switch_on
        ? t("blockedSwitch")
        : !shown.link_on
          ? t("blockedLink")
          : (shown.problem ?? shown.data?.problem ?? null);
  const reason = refusal ?? blocked;
  const fingerprint = shown?.fingerprint ?? null;
  const ready = shown !== undefined && shown.confirmable && fingerprint !== null;

  const close = () => {
    setRefusal(null);
    onOpenChange(false);
  };

  const confirm = async (fingerprint: string, digest: string) => {
    try {
      await onConfirm(fingerprint, digest);
      close();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        close();
        return;
      }
      setRefusal(getErrorMessage(error, tErrors));
      void disclosure.refetch();
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setRefusal(null);
        onOpenChange(next);
      }}
    >
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("confirmTitle")}</DialogTitle>
          <DialogDescription>{t("confirmWhy")}</DialogDescription>
        </DialogHeader>
        {disclosure.isLoading ? (
          <LoadingState variant="skeleton-panel" rows={4} />
        ) : shown === undefined ? (
          <ErrorState title={t("disclosureFailed")} />
        ) : (
          <div className="space-y-4 text-sm">
            {shown.data !== null && <ConsentQueries disclosure={shown.data} />}
            <PublicAudience shown={shown} />
          </div>
        )}
        {reason !== null && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{reason}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            disabled={loading || !ready || reason !== null}
            onClick={
              ready && shown !== undefined
                ? () => void confirm(fingerprint, shown.audience_digest)
                : undefined
            }
          >
            {t("confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
