"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link2, Unplug } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, ConfirmDialog } from "@/components/ui";
import type { PortalWithState } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { disconnectPortal, fetchMicrosoftAdminConsentUrl } from "@/lib/mcp-connections-api";
import { qk } from "@/lib/query-keys";

/**
 * The account half of a polled portal's card: disconnecting it, and the link a
 * Microsoft 365 administrator approves the organization's app at.
 *
 * Rendered only for a caller holding `mcp:manage`, which both routes require.
 * Disconnect is offered on a polled portal, whose account is nothing but its
 * grant; a webhook portal's account also carries the hooks it registered, and
 * is removed where it was connected.
 */
export function PortalAccountControls({ item }: { item: PortalWithState }) {
  const t = useTranslations("portals");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function copyAdminConsentLink() {
    try {
      await navigator.clipboard.writeText(await fetchMicrosoftAdminConsentUrl());
      toast.success(t("adminConsentCopied"));
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("adminConsentFailed")));
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await disconnectPortal(item.portal.key);
      await queryClient.invalidateQueries({ queryKey: qk.portals.catalog() });
      toast.success(t("disconnected", { name: item.portal.name }));
      setConfirming(false);
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("disconnectFailed")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {/* Offered before anyone has connected too: an administrator can approve
          the app for the tenant ahead of the first member, which is what spares
          that member Entra's "Need admin approval" screen. */}
      {item.portal.key === "microsoft" && item.portal.connect_blocked_by === null && (
        <Button size="sm" variant="ghost" onClick={copyAdminConsentLink}>
          <Link2 className="mr-1 h-3.5 w-3.5" />
          {t("copyAdminConsentLink")}
        </Button>
      )}
      {item.portal.delivery === "polling" && item.connectionId !== null && (
        <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
          <Unplug className="mr-1 h-3.5 w-3.5" />
          {t("disconnectAction")}
        </Button>
      )}
      {confirming && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && !busy && setConfirming(false)}
          title={t("disconnectTitle", { name: item.portal.name })}
          description={t("disconnectWarning", { name: item.portal.name })}
          confirmLabel={t("disconnectAction")}
          destructive
          loading={busy}
          onConfirm={disconnect}
        />
      )}
    </>
  );
}
