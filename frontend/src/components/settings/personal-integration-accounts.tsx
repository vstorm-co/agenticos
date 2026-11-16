"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, ConfirmDialog } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { ConnectedAccountPicker } from "@/components/vault/connected-account-picker";
import { SectionCard } from "./settings-section";
import {
  ConnectedAccountSetup,
  type AccountSetupTarget,
} from "@/components/vault/connected-account-setup";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import { useMcpOAuthOutcome } from "@/hooks/use-mcp-oauth-outcome";
import { hereForMcpOAuthReturn } from "@/lib/mcp-oauth";
import { getErrorMessage } from "@/lib/api-error";
import type { ConnectedAccount } from "@/types/mirage";

/** Personal accounts stay manageable without opening an agent or the organization's Vault. */
export function PersonalIntegrationAccounts() {
  const t = useTranslations("pages.vault.connectedAccounts");
  const errors = useTranslations("errors");
  const accounts = useConnectedAccounts("personal", { provider: "all" });
  const [picking, setPicking] = useState(false);
  const [setup, setSetup] = useState<AccountSetupTarget | null>(null);
  const [disconnecting, setDisconnecting] = useState<ConnectedAccount | null>(null);
  useMcpOAuthOutcome();
  return (
    <SectionCard
      title={t("personalTitle")}
      description={t("personalDescription")}
      tour="personal-integration-accounts"
      action={
        <Button variant="outline" size="sm" onClick={() => setPicking(true)}>
          {t("addAccount")}
        </Button>
      }
    >
      {accounts.isLoading && <LoadingState variant="skeleton-list" rows={1} />}
      {accounts.error && <ErrorState description={getErrorMessage(accounts.error, errors)} />}
      {!accounts.isLoading && !accounts.error && accounts.accounts.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("noPersonalAccounts")}</p>
      )}
      <div className="space-y-3">
        {accounts.accounts.map((account) => (
          <div key={account.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
            <ProviderIcon provider={account.provider} brand={account.provider} />
            <div className="min-w-0 flex-1 text-sm">
              <p className="break-words">
                {account.label ? `${account.label} — ${account.email}` : account.email}
              </p>
              <p className="text-muted-foreground text-xs">
                {account.needs_reconnect
                  ? t("needsReconnect")
                  : account.polling_failed
                    ? t("pollingFailed")
                    : t(`setup.provider.${account.provider}`)}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              aria-label={t(
                account.needs_reconnect || account.polling_failed
                  ? "reconnectNamed"
                  : "updateAccessNamed",
                { email: account.email },
              )}
              onClick={() =>
                setSetup({
                  owner: "personal",
                  provider: account.provider,
                  account,
                  returnTo: hereForMcpOAuthReturn(),
                })
              }
            >
              {account.needs_reconnect || account.polling_failed
                ? t("reconnect")
                : t("updateAccess")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setDisconnecting(account)}>
              {t("disconnectConfirm")}
            </Button>
          </div>
        ))}
      </div>
      {picking && (
        <ConnectedAccountPicker
          onClose={() => setPicking(false)}
          onSelect={(target) => {
            setPicking(false);
            setSetup({ ...target, returnTo: hereForMcpOAuthReturn() });
          }}
        />
      )}
      {setup && <ConnectedAccountSetup target={setup} onClose={() => setSetup(null)} />}
      {disconnecting && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setDisconnecting(null)}
          title={t("disconnectTitle", { email: disconnecting.email })}
          description={t("disconnectDetail")}
          confirmLabel={t("disconnectConfirm")}
          destructive
          onConfirm={() => {
            accounts.disconnect(disconnecting.id);
            setDisconnecting(null);
          }}
        />
      )}
    </SectionCard>
  );
}
