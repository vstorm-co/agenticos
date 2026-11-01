"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ConfirmDataDialog } from "@/components/artifacts/confirm-data-dialog";
import { ConsentNotice, confirmer } from "@/components/artifacts/consent-notice";
import { ConfirmDialog } from "@/components/ui";
import type { ArtifactConsent } from "@/types/artifact";

interface ConsentControlsProps {
  artifactId: string;
  /** The latest version, which the caller is served and whose data is confirmed. */
  versionId: string;
  consent: ArtifactConsent;
  isOwner: boolean;
  /** Whether the strip line is drawn: only over the latest version. */
  showNotice: boolean;
  /** A version request for this version waits for review, which is where it is confirmed. */
  reviewPending: boolean;
  /** Withdraw's question, open - from the strip here or from the page's menu. */
  withdrawing: boolean;
  onWithdrawingChange: (open: boolean) => void;
  onConfirm: (fingerprint: string) => Promise<unknown>;
  confirmPending: boolean;
  onWithdraw: (onDone: () => void) => void;
  withdrawPending: boolean;
}

/**
 * The page's consent, for a caller served its latest version: the strip line, the
 * Confirm data dialog and the question Withdraw asks first - saying that the
 * audience keeps the page and loses its data until it is confirmed again.
 */
export function ConsentControls({
  artifactId,
  versionId,
  consent,
  isOwner,
  showNotice,
  reviewPending,
  withdrawing,
  onWithdrawingChange,
  onConfirm,
  confirmPending,
  onWithdraw,
  withdrawPending,
}: ConsentControlsProps) {
  const t = useTranslations("artifacts.consent");
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      {showNotice && (
        <ConsentNotice
          consent={consent}
          isOwner={isOwner}
          reviewPending={reviewPending}
          onConfirm={() => setConfirming(true)}
          onWithdraw={() => onWithdrawingChange(true)}
        />
      )}
      {consent.may_confirm && (
        <ConfirmDataDialog
          artifactId={artifactId}
          versionId={versionId}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={onConfirm}
          loading={confirmPending}
        />
      )}
      <ConfirmDialog
        open={withdrawing}
        onOpenChange={onWithdrawingChange}
        title={t("withdrawTitle")}
        description={t("withdrawWhy", {
          who: confirmer(consent, isOwner),
          owner: consent.owner_name ?? "",
        })}
        confirmLabel={t("withdraw")}
        destructive
        loading={withdrawPending}
        onConfirm={() => onWithdraw(() => onWithdrawingChange(false))}
      />
    </>
  );
}
