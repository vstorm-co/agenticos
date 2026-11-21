"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";
import { Button, Checkbox, Label } from "@/components/ui";
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
  const [selected, setSelected] = useState<readonly SubscriptionProvider[]>([]);
  const [connecting, setConnecting] = useState<SubscriptionProvider | null>(null);
  if (actions.accounts.data?.enabled === false) return null;
  return (
    <section className="border-border space-y-3 border-t py-4" data-tour="start-subscriptions">
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
        <ul className="divide-border divide-y">
          {SUBSCRIPTION_PROVIDERS.map((provider) => {
            const connected =
              actions.accounts.data?.items.some(
                (account) =>
                  subscriptionBelongsTo(account, provider) &&
                  !account.disabled &&
                  !account.unavailable,
              ) ?? false;
            const picked = selected.includes(provider);
            return (
              <li key={provider} className="flex min-h-12 items-center gap-3 py-2">
                <Checkbox
                  id={`start-subscription-${provider}`}
                  checked={connected || picked}
                  disabled={connected || !actions.ready || actions.accounts.isLoading}
                  onCheckedChange={(checked) =>
                    setSelected((previous) =>
                      checked === true
                        ? [...previous, provider]
                        : previous.filter((entry) => entry !== provider),
                    )
                  }
                />
                <ProviderIcon provider={SUBSCRIPTION_MARK[provider]} className="size-5 shrink-0" />
                <Label htmlFor={`start-subscription-${provider}`} className="flex-1">
                  {accountsCopy(`providers.${provider}`)}
                </Label>
                {connected ? (
                  <span className="text-success flex items-center gap-1.5 text-xs">
                    <Check className="size-3.5" aria-hidden />
                    {t("connected")}
                  </span>
                ) : picked ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setConnecting(provider)}
                  >
                    {accountsCopy("connect")}
                  </Button>
                ) : null}
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
