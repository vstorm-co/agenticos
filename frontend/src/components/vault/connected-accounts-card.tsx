"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Plus, Trash2, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Button, ConfirmDialog, IconButton, ListCard, ListCardEmpty } from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useConnectedAccounts, type AccountOwner } from "@/hooks/use-connected-accounts";
import { getErrorMessage } from "@/lib/api-error";
import type { ConnectedAccount } from "@/types/mirage";

interface ConnectedAccountsCardProps {
  owner: AccountOwner;
  /** Whether the caller may connect and disconnect here; listing is the card's to show. */
  canManage: boolean;
}

/**
 * One owner's connected accounts: the Google sign-ins a virtual terminal's folder
 * reads as (#2191).
 *
 * A person's own are what an agent mounting "each person's own accounts" finds
 * when that person talks to it; the organization's are the ones an author can
 * point a folder at for everybody. No token is ever shown - the grant is sealed
 * in the vault, and a row is its address and whether it still works.
 */
export function ConnectedAccountsCard({ owner, canManage }: ConnectedAccountsCardProps) {
  const t = useTranslations("pages.vault.connectedAccounts");
  const tErrors = useTranslations("errors");
  const returnTo = usePathname();
  const { accounts, isLoading, error, connect, isConnecting, disconnect } =
    useConnectedAccounts(owner);
  const [removing, setRemoving] = useState<ConnectedAccount | null>(null);

  const connectButton = canManage ? (
    <Button size="sm" variant="outline" disabled={isConnecting} onClick={() => connect(returnTo)}>
      <Plus className="h-3.5 w-3.5" />
      {t("connect")}
    </Button>
  ) : undefined;

  return (
    <ListCard
      title={t(owner === "personal" ? "personalTitle" : "organizationTitle")}
      counted={isLoading || error ? null : t("count", { count: accounts.length })}
      controls={accounts.length > 0 ? connectButton : undefined}
      contentClassName="p-0"
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
      ) : accounts.length === 0 ? (
        <ListCardEmpty
          icon={UserRound}
          title={t("noneYet")}
          description={t(owner === "personal" ? "personalDetail" : "organizationDetail")}
          cta={
            canManage
              ? {
                  label: (
                    <>
                      <Plus className="h-3.5 w-3.5" />
                      {t("connect")}
                    </>
                  ),
                  onClick: () => connect(returnTo),
                }
              : undefined
          }
        />
      ) : (
        <ul>
          {accounts.map((account) => (
            <li
              key={account.id}
              className="border-border flex items-center gap-3 border-b px-5 py-3 last:border-b-0"
            >
              <ProviderIcon provider={account.provider} className="h-5 w-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{account.email}</p>
                {account.needs_reconnect ? (
                  <p className="text-destructive text-xs">{t("needsReconnect")}</p>
                ) : (
                  <p className="text-muted-foreground text-xs">
                    {t("scopes", { count: account.scopes.length })}
                  </p>
                )}
              </div>
              {canManage && account.needs_reconnect && (
                <Button size="sm" variant="outline" onClick={() => connect(returnTo)}>
                  {t("reconnect")}
                </Button>
              )}
              {canManage && (
                <IconButton
                  variant="ghost"
                  aria-label={t("disconnect", { email: account.email })}
                  onClick={() => setRemoving(account)}
                >
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              )}
            </li>
          ))}
        </ul>
      )}

      {removing && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setRemoving(null)}
          title={t("disconnectTitle", { email: removing.email })}
          description={t("disconnectDetail")}
          confirmLabel={t("disconnectConfirm")}
          destructive
          onConfirm={() => {
            disconnect(removing.id);
            setRemoving(null);
          }}
        />
      )}
    </ListCard>
  );
}
