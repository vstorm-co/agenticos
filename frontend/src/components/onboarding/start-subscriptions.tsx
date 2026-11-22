"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";
import { Button, Badge } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { SubscriptionSignInDialog } from "@/components/settings/subscription-accounts";
import { useSubscriptionAccounts } from "@/hooks/use-subscription-accounts";
import {
  SUBSCRIPTION_PROVIDERS,
  SUBSCRIPTION_MARK,
  subscriptionBelongsTo,
  type SubscriptionProvider,
} from "@/lib/subscription-accounts-api";

/** Personal connections stay optional and never become the organization's shared model. */
export function StartSubscriptions() {
  const t = useTranslations("start.subscriptions");
  const accountsCopy = useTranslations("subscriptionAccounts");
  const actions = useSubscriptionAccounts();
  const [connecting, setConnecting] = useState<SubscriptionProvider | null>(null);
  if (actions.accounts.data?.enabled === false) return null;
  return (
    <section className="space-y-4 py-4" data-tour="start-subscriptions">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">{t("title")}</h2>
        <p className="text-muted-foreground text-xs">{t("description")}</p>
      </div>
      {actions.accounts.error ? (
        <ErrorState
          title={accountsCopy("loadFailed")}
          cta={{ label: accountsCopy("retry"), onClick: () => void actions.accounts.refetch() }}
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {SUBSCRIPTION_PROVIDERS.map((provider) => {
            const connected =
              actions.accounts.data?.items.some(
                (account) =>
                  subscriptionBelongsTo(account, provider) &&
                  !account.disabled &&
                  !account.unavailable,
              ) ?? false;
            return (
              <li
                key={provider}
                className="border-border flex flex-wrap items-center gap-3 rounded-xl border p-4"
              >
                <ProviderIcon provider={SUBSCRIPTION_MARK[provider]} className="size-5 shrink-0" />
                <span className="min-w-0 flex-1 text-sm font-medium">
                  {accountsCopy(`providers.${provider}`)}
                </span>
                {connected && (
                  <Badge variant="success">
                    <Check className="size-3" aria-hidden />
                    {t("connected")}
                  </Badge>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!actions.ready || actions.accounts.isLoading}
                  onClick={() => setConnecting(provider)}
                >
                  {accountsCopy(connected ? "connectAnother" : "connect")}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-muted-foreground text-xs">{t("hint")}</p>
      {connecting && (
        <SubscriptionSignInDialog
          key={`${actions.scope}:${connecting}`}
          provider={connecting}
          actions={actions}
          onClose={() => setConnecting(null)}
        />
      )}
    </section>
  );
}
