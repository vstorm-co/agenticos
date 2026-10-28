"use client";

import { useState } from "react";
import { CheckCircle2, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { BrandIcon } from "@/components/icons/brand-icon";
import Link from "next/link";

import { MailboxInterval } from "@/components/triggers/mailbox-interval";
import { Button, Skeleton } from "@/components/ui";
import { usePermissions, usePortals } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { portalConnectUrl } from "@/lib/portal-connect";
import { Perm } from "@/types/permissions";

/** Which portal's account a trigger listens through, and the mark that shows it. */
export interface TriggerAccount {
  portal: string;
  brand: "gmail" | "microsoft" | "github";
}

/** The trigger steps that listen through a connected account. */
export const ACCOUNT_TRIGGERS: Record<string, TriggerAccount> = {
  "trigger.gmail": { portal: "google", brand: "gmail" },
  "trigger.outlook": { portal: "microsoft", brand: "microsoft" },
  "trigger.github": { portal: "github", brand: "github" },
};

/**
 * The organization's account a trigger step listens through, and connecting it.
 *
 * A Gmail or Outlook trigger has nothing to listen to until a mailbox is connected, and a
 * GitHub trigger registers its own hook only through an account that may manage
 * webhooks - so the step says which it has, where the builder is, rather than
 * leaving it to a refused publish or a hook nobody registered. Connecting is the
 * portal catalog's own flow, and needs `mcp:manage` as it does there.
 */
export function PortalAccount({ account }: { account: TriggerAccount }) {
  const t = useTranslations("workflows.portalAccount");
  const tPortals = useTranslations("portals");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { items, isLoading } = usePortals();
  const [busy, setBusy] = useState(false);
  const item = items.find((one) => one.portal.key === account.portal);

  if (isLoading) return <Skeleton className="h-14 w-full" />;
  if (item === undefined) return null;

  const ready = item.action === "create";
  const blockedBy = item.portal.connect_blocked_by;

  const connect = async () => {
    setBusy(true);
    try {
      window.location.assign(await portalConnectUrl(item));
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, tPortals("couldNotConnect")));
      setBusy(false);
    }
  };

  return (
    <div className="flex items-start gap-3 rounded-lg border p-3">
      <BrandIcon name={account.brand} className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          {item.portal.name}
          {ready && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />}
        </p>
        <p className="text-muted-foreground text-xs">
          {t(`${account.brand}.${ready ? "ready" : item.action}`)}
        </p>
        {!ready && blockedBy !== null && (
          <p className="text-muted-foreground text-xs">
            {t(`blocked.${blockedBy}`, { portal: item.portal.name })}{" "}
            {blockedBy !== "oauth_unavailable" && (
              <Link href={ROUTES.VAULT} className="underline underline-offset-2">
                {t("openVault")}
              </Link>
            )}
          </p>
        )}
        {ready && account.brand !== "github" && (
          <div className="pt-1">
            <MailboxInterval portal={item.portal} canManage={can(Perm.mcpManage)} />
          </div>
        )}
      </div>
      {!ready && blockedBy === null && can(Perm.mcpManage) && (
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void connect()}>
          <Plug className="h-4 w-4" />
          {t(item.action === "connect" ? "connect" : "reconnect")}
        </Button>
      )}
    </div>
  );
}
