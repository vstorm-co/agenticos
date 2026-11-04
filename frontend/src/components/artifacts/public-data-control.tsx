"use client";

import { useState } from "react";
import { ShieldAlert } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ViewerNotice } from "@/components/artifacts/live-data-controls";
import { PublicDataDialog } from "@/components/artifacts/public-data-dialog";
import { Button, ConfirmDialog } from "@/components/ui";
import type { ArtifactDetail, PublicDataNotHolding } from "@/types/artifact";

const NOT_HOLDING_TEXT = {
  switch_off: "notHoldingSwitchOff",
  no_served_version: "notHoldingNoServedVersion",
  queries_changed: "notHoldingQueriesChanged",
  owner_gone: "notHoldingOwnerGone",
  owner_membership_changed: "notHoldingOwnerMembershipChanged",
  member_consent_missing: "notHoldingMemberConsentMissing",
  link_expired: "notHoldingLinkExpired",
} as const satisfies Record<PublicDataNotHolding, string>;

/** Whether the page's public data was confirmed, is still on, and its queries moved since. */
export function queryMoved(artifact: ArtifactDetail): boolean {
  return artifact.public_data?.not_holding === "queries_changed";
}

interface PublicDataActionsProps {
  artifact: ArtifactDetail;
  onConfirm: (fingerprint: string, audienceDigest: string) => Promise<unknown>;
  confirmPending: boolean;
}

/**
 * The strip line for an editor: the page's confirmed public data went blank because
 * its queries changed, and stays blank until somebody who may confirms it again.
 */
export function PublicDataNotice({ artifact, onConfirm, confirmPending }: PublicDataActionsProps) {
  const t = useTranslations("artifacts.publicData");
  const [confirming, setConfirming] = useState(false);
  if (!queryMoved(artifact)) return null;
  return (
    <>
      <ViewerNotice tone="warning" icon={ShieldAlert} tour="artifact-public-data">
        <span>{t("queryChangedNotice")}</span>
        {artifact.may_confirm_public_data && (
          <Button size="sm" className="h-6 px-2" onClick={() => setConfirming(true)}>
            {t("confirm")}
          </Button>
        )}
      </ViewerNotice>
      {artifact.may_confirm_public_data && (
        <PublicDataDialog
          artifactId={artifact.id}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={onConfirm}
          loading={confirmPending}
        />
      )}
    </>
  );
}

interface PublicDataControlProps extends PublicDataActionsProps {
  onWithdraw: (onDone: () => void) => void;
  withdrawPending: boolean;
}

/**
 * "Live data on this public link", in the share dialog under the link's settings,
 * for a page that reads table data and has a link. Where it stands, said in words,
 * and what the caller may do: Confirm (the owner, or an Owner or Admin for them -
 * the server's `may_confirm_public_data`), Withdraw (any editor, which only narrows).
 * With the organization's switch off nothing can be done here, and it says who can.
 */
export function PublicDataControl({
  artifact,
  onConfirm,
  confirmPending,
  onWithdraw,
  withdrawPending,
}: PublicDataControlProps) {
  const t = useTranslations("artifacts.publicData");
  const format = useFormatter();
  const [confirming, setConfirming] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const data = artifact.public_data;
  // A consent outlives a version that reads no data, so Withdraw stays while it stands.
  if (
    data === null ||
    !(data.consented || artifact.bindings.length > 0) ||
    artifact.public_url === null
  ) {
    return null;
  }

  const confirmButton = (label: string) =>
    artifact.may_confirm_public_data && (
      <Button size="sm" onClick={() => setConfirming(true)}>
        {label}
      </Button>
    );
  const withdrawButton = artifact.can_edit && (
    <Button size="sm" variant="outline" onClick={() => setWithdrawing(true)}>
      {t("withdraw")}
    </Button>
  );

  let status: string;
  let actions: React.ReactNode = null;
  if (!data.consented) {
    status = !data.switch_on
      ? t("stateSwitchOff")
      : artifact.may_confirm_public_data
        ? t("stateNotConfirmed")
        : t("stateOwnerCanEnable");
    actions = data.switch_on && confirmButton(t("confirm"));
  } else if (data.holds) {
    status = t("stateHolding", {
      version: data.version ?? 0,
      name: data.by_name ?? "",
      date: data.at === null ? "" : format.dateTime(new Date(data.at), { dateStyle: "medium" }),
    });
    actions = withdrawButton;
  } else {
    // A consent with nothing to say why can only be a server older than this console.
    status = t(NOT_HOLDING_TEXT[data.not_holding ?? "queries_changed"]);
    actions = (
      <>
        {data.not_holding === "queries_changed" && confirmButton(t("confirmAgain"))}
        {withdrawButton}
      </>
    );
  }

  return (
    <div className="space-y-2 border-t pt-4" data-testid="public-data-control">
      <p className="text-sm font-medium">{t("title")}</p>
      <p className="text-muted-foreground text-sm">{status}</p>
      {actions !== null && actions !== false && (
        <div className="flex flex-wrap gap-2">{actions}</div>
      )}
      {artifact.may_confirm_public_data && (
        <PublicDataDialog
          artifactId={artifact.id}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={onConfirm}
          loading={confirmPending}
        />
      )}
      <ConfirmDialog
        open={withdrawing}
        onOpenChange={setWithdrawing}
        title={t("withdrawTitle")}
        description={t("withdrawWhy")}
        confirmLabel={t("withdraw")}
        destructive
        loading={withdrawPending}
        onConfirm={() => onWithdraw(() => setWithdrawing(false))}
      />
    </div>
  );
}
