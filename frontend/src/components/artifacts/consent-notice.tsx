"use client";

import { ShieldAlert, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { ViewerNotice } from "@/components/artifacts/live-data-controls";
import { Button } from "@/components/ui";
import type { ArtifactConsent } from "@/types/artifact";

/** How a sentence names whoever confirms: the viewer, the owner by name, or neither. */
export function confirmer(consent: ArtifactConsent, isOwner: boolean): "you" | "unknown" | "named" {
  if (isOwner) return "you";
  return consent.owner_name === null ? "unknown" : "named";
}

interface ConsentNoticeProps {
  consent: ArtifactConsent;
  /** The viewer owns the page, so the notice speaks to them. */
  isOwner: boolean;
  /**
   * An editor's republish of this version waits for review. Its review strip shows
   * what changed, so Confirm is not offered here: it would let the owner skip the diff.
   */
  reviewPending: boolean;
  onConfirm: () => void;
  onWithdraw: () => void;
}

/**
 * Where the latest version's data stands with the page's owner, when that needs
 * attention: a version waiting for consent - with what the audience sees meanwhile -
 * or one consented automatically that reaches more than the version before it.
 *
 * Drawn only for a caller served the latest version (the server sends `consent`
 * to nobody else). Confirm is offered to whoever may confirm (the owner, or an
 * Owner or Admin for them) and Withdraw to an editor while the audience still
 * reads data - both the server's answer, never worked out here.
 */
export function ConsentNotice({
  consent,
  isOwner,
  reviewPending,
  onConfirm,
  onWithdraw,
}: ConsentNoticeProps) {
  const t = useTranslations("artifacts.consent");
  const who = confirmer(consent, isOwner);
  const withdraw = consent.may_withdraw && consent.shared && (
    <Button size="sm" variant="outline" className="h-6 px-2" onClick={onWithdraw}>
      {t("withdraw")}
    </Button>
  );

  if (consent.state === "consented") {
    if (!consent.automatic || consent.grown.length === 0 || !consent.may_confirm) return null;
    return (
      <ViewerNotice tone="info" icon={Sparkles}>
        <span>
          {consent.via === null
            ? t("grownAutomatically", {
                version: consent.version,
                added: consent.grown.join(", "),
              })
            : t("grownAutomaticallyVia", {
                version: consent.version,
                name: consent.via,
                added: consent.grown.join(", "),
              })}
        </span>
        {withdraw}
      </ViewerNotice>
    );
  }

  const audience = consent.audience_version === null ? "none" : String(consent.audience_version);
  const sentence = { who, owner: consent.owner_name ?? "" };
  return (
    <ViewerNotice tone="warning" icon={ShieldAlert} tour="artifact-consent">
      <span>
        {consent.state === "withdrawn"
          ? `${t("withdrawnState")} ${t("audienceWithoutData", { ...sentence, audience })}`
          : `${t("pendingState", { version: consent.version })} ${t("audienceWaits", { ...sentence, audience })}`}
      </span>
      {consent.may_confirm && !reviewPending && (
        <Button size="sm" className="h-6 px-2" onClick={onConfirm}>
          {t("confirm")}
        </Button>
      )}
      {withdraw}
    </ViewerNotice>
  );
}
