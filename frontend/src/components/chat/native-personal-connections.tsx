"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { ProviderIcon } from "@/components/vault/provider-icon";
import {
  ConnectedAccountSetup,
  type AccountSetupTarget,
} from "@/components/vault/connected-account-setup";
import { useCapabilityCatalog } from "@/hooks/use-agents";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import { hereForMcpOAuthReturn } from "@/lib/mcp-oauth";
import { getErrorMessage } from "@/lib/api-error";
import type { CapabilityBindingSpec } from "@/types/agents";

/** Personal native accounts can be added and repaired without leaving the conversation. */
export function NativePersonalConnections({ bindings }: { bindings: CapabilityBindingSpec[] }) {
  const t = useTranslations("chat.personalServices");
  const ta = useTranslations("pages.vault.connectedAccounts");
  const errors = useTranslations("errors");
  const { capabilities, error: catalogError } = useCapabilityCatalog();
  const products = bindings.flatMap((binding) => {
    const entry = capabilities.find((item) => item.id === binding.id);
    const provider = entry?.config_schema?.["x-integration-provider"];
    return binding.enabled !== false &&
      binding.config.account !== "organization" &&
      provider &&
      entry
      ? [{ binding, provider, name: entry.name }]
      : [];
  });
  const { accounts, isLoading, error } = useConnectedAccounts("personal", {
    provider: "all",
    enabled: products.length > 0,
  });
  const [setup, setSetup] = useState<AccountSetupTarget | null>(null);
  if (products.length === 0)
    return catalogError ? <ErrorState description={getErrorMessage(catalogError, errors)} /> : null;
  return (
    <div className="border-foreground/10 mt-4 space-y-3 border-t pt-4">
      <p className="text-muted-foreground text-xs">{t("nativeAccounts")}</p>
      {catalogError && <ErrorState description={getErrorMessage(catalogError, errors)} />}
      {error && <ErrorState description={getErrorMessage(error, errors)} />}
      <ul className="space-y-3">
        {products.map(({ binding, provider, name }) => {
          const held = accounts.filter((account) => account.provider === provider);
          const exact = held.filter((account) => account.name === binding.config.account_name);
          const matching = exact.length
            ? exact
            : held.filter(
                (account) =>
                  !binding.config.account_name ||
                  [account.label, account.email].includes(String(binding.config.account_name)),
              );
          return (
            <li key={binding.id} aria-label={name} className="space-y-2 rounded-xl px-3 py-2">
              <div className="flex items-center gap-2">
                <ProviderIcon provider={provider} brand={provider} />
                <span className="min-w-0 flex-1 text-xs font-medium">{name}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={isLoading}
                  onClick={() =>
                    setSetup({
                      owner: "personal",
                      provider,
                      products: [binding.id],
                      returnTo: hereForMcpOAuthReturn(),
                    })
                  }
                >
                  {matching.length ? t("addAccount") : t("connect")}
                </Button>
              </div>
              {!isLoading && !error && matching.length === 0 && (
                <p className="text-muted-foreground text-xs">{t("status.not_connected")}</p>
              )}
              {matching.map((account) => (
                <div key={account.id} className="flex items-center gap-2 text-xs">
                  <span className="min-w-0 flex-1 break-words">
                    {account.label ? `${account.label} — ${account.email}` : account.email}
                    <span className="text-muted-foreground block">
                      {account.needs_reconnect
                        ? ta("needsReconnect")
                        : account.polling_failed
                          ? ta("pollingFailed")
                          : t("status.connected")}
                    </span>
                  </span>
                  {(account.needs_reconnect || account.polling_failed) && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      aria-label={ta("reconnectNamed", { email: account.email })}
                      onClick={() =>
                        setSetup({
                          owner: "personal",
                          provider,
                          account,
                          products: [binding.id],
                          returnTo: hereForMcpOAuthReturn(),
                        })
                      }
                    >
                      {ta("reconnect")}
                    </Button>
                  )}
                </div>
              ))}
            </li>
          );
        })}
      </ul>
      {setup && <ConnectedAccountSetup target={setup} onClose={() => setSetup(null)} />}
    </div>
  );
}
