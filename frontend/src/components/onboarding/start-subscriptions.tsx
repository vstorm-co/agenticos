"use client";

import { useStartVariant } from "./start-experience";
import { useId, useState } from "react";
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
import styles from "./start-subscriptions.module.css";

/** Personal connections stay optional and never become the organization's shared model. */
export function StartSubscriptions() {
  const variant = useStartVariant();
  const t = useTranslations("start.subscriptions");
  const accountsCopy = useTranslations("subscriptionAccounts");
  const actions = useSubscriptionAccounts();
  const id = useId();
  const [connecting, setConnecting] = useState<SubscriptionProvider | null>(null);
  if (actions.accounts.data?.enabled === false) return null;
  return (
    <section className="space-y-4 py-4" data-tour="start-subscriptions">
      {variant !== "studio" && (
        <div className="space-y-1">
          <h2 className="text-sm font-medium">{t("title")}</h2>
          <p className="text-muted-foreground text-xs">{t("description")}</p>
        </div>
      )}
      {actions.accounts.error ? (
        <ErrorState
          title={accountsCopy("loadFailed")}
          cta={{ label: accountsCopy("retry"), onClick: () => void actions.accounts.refetch() }}
        />
      ) : (
        <ul className={styles.services}>
          {SUBSCRIPTION_PROVIDERS.map((provider) => {
            const connected =
              actions.accounts.data?.items.some(
                (account) =>
                  subscriptionBelongsTo(account, provider) &&
                  !account.disabled &&
                  !account.unavailable,
              ) ?? false;
            const name = accountsCopy(`providers.${provider}`);
            return (
              <li key={provider}>
                <article className={styles.service} aria-labelledby={`${id}-${provider}`}>
                  <header className={styles.identity}>
                    <ProviderIcon provider={SUBSCRIPTION_MARK[provider]} className={styles.logo} />
                    <div className={styles.name}>
                      <h3 id={`${id}-${provider}`}>{name}</h3>
                      {connected && (
                        <Badge variant="success">
                          <Check className="size-3" aria-hidden />
                          {t("connected")}
                        </Badge>
                      )}
                    </div>
                  </header>
                  <footer className={styles.actions}>
                    <Button
                      type="button"
                      variant={connected ? "ghost" : "outline"}
                      size="sm"
                      aria-label={`${accountsCopy(connected ? "connectAnother" : "connect")} ${name}`}
                      disabled={!actions.ready || actions.accounts.isLoading}
                      onClick={() => setConnecting(provider)}
                    >
                      {accountsCopy(connected ? "connectAnother" : "connect")}
                    </Button>
                  </footer>
                </article>
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
