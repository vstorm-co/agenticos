"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConsentDisclosure } from "@/components/artifacts/consent-disclosure";
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
import { useArtifactDisclosure } from "@/hooks/use-artifacts";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

interface ConfirmDataDialogProps {
  artifactId: string;
  /** The latest version, whose data is confirmed. */
  versionId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Sends the fingerprint the person was shown; rejects with the server's refusal. */
  onConfirm: (fingerprint: string) => Promise<unknown>;
  loading: boolean;
}

/**
 * "Confirm data": what the version's page queries share and with whom, then the
 * confirmation - which carries the fingerprint of exactly what was shown, so a
 * page republished in between is refused rather than confirmed unseen. A 409 means
 * a newer version landed or the queries moved: the page is read again by the
 * mutation and the dialog closes, so the person looks at the new latest. Any other
 * refusal is shown here, with the disclosure read again, and holds the button, as
 * does the server's `problem` (the owner left, or can't read a table).
 */
export function ConfirmDataDialog({
  artifactId,
  versionId,
  open,
  onOpenChange,
  onConfirm,
  loading,
}: ConfirmDataDialogProps) {
  const t = useTranslations("artifacts.consent");
  const tErrors = useTranslations("errors");
  const [refusal, setRefusal] = useState<string | null>(null);
  const disclosure = useArtifactDisclosure(artifactId, versionId, open);
  const shown = disclosure.data;
  const fingerprint = shown?.fingerprint ?? null;
  const problem = refusal ?? shown?.problem ?? null;

  const close = () => {
    setRefusal(null);
    onOpenChange(false);
  };

  const confirm = async (seen: string) => {
    try {
      await onConfirm(seen);
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
          <DialogTitle>
            {shown === undefined
              ? t("confirmTitleUnnumbered")
              : t("confirmTitle", { version: shown.version })}
          </DialogTitle>
          <DialogDescription>{t("confirmWhy")}</DialogDescription>
        </DialogHeader>
        {disclosure.isLoading ? (
          <LoadingState variant="skeleton-panel" rows={4} />
        ) : shown === undefined ? (
          <ErrorState title={t("disclosureFailed")} />
        ) : (
          <ConsentDisclosure disclosure={shown} />
        )}
        {problem !== null && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            disabled={loading || fingerprint === null || problem !== null}
            onClick={fingerprint === null ? undefined : () => void confirm(fingerprint)}
          >
            {t("confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
