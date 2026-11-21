"use client";

import { useId, useState, useRef, useLayoutEffect } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button, FormField } from "@/components/ui";
import { CircleCheck } from "lucide-react";
import { ErrorState } from "@/components/states";
import { ModelCombobox } from "./model-combobox";
import { SubscriptionSignInDialog } from "@/components/settings/subscription-accounts";
import { useSubscriptionAccounts, useSubscriptionModels } from "@/hooks/use-subscription-accounts";
import { useModelProviders } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { runsAgents } from "@/lib/model-profiles";
import { subscriptionBelongsTo, type SubscriptionProvider } from "@/lib/subscription-accounts-api";
import type { ModelProfile } from "@/types/providers";

/** A subscription supplies models to AgenticOS; it does not enable a separate harness. */
export function SubscriptionModelForm({
  provider,
  initialModel = "",
  onCreated,
  disabled,
  onPendingChange,
}: {
  provider: SubscriptionProvider;
  initialModel?: string;
  onCreated: (profile: ModelProfile) => void;
  disabled?: boolean;
  onPendingChange?: (pending: boolean) => void;
}) {
  const t = useTranslations("modelSources");
  const accountsCopy = useTranslations("subscriptionAccounts");
  const errors = useTranslations("errors");
  const agents = useTranslations("agents");
  const id = useId();
  const actions = useSubscriptionAccounts();
  const listing = useSubscriptionModels(provider);
  const { createProfile, profiles } = useModelProviders();
  const [connecting, setConnecting] = useState(false);
  const [model, setModel] = useState(initialModel);
  const [failure, setFailure] = useState<string | null>(null);
  const active = useRef(true);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const own = (actions.accounts.data?.items ?? []).filter((account) =>
    subscriptionBelongsTo(account, provider),
  );
  const connected = own.some((account) => !account.disabled && !account.unavailable);
  const choose = async () => {
    onPendingChange?.(true);
    setFailure(null);
    try {
      const existing = profiles.find(
        (entry) =>
          entry.provider === "subscription_accounts" && entry.model === model && runsAgents(entry),
      );
      const profile =
        existing ??
        (await createProfile.mutateAsync({
          provider: "subscription_accounts",
          model,
          secret_id: null,
          label: `${accountsCopy(`providers.${provider}`)} · ${model}`,
        }));
      if (!active.current) return;
      if (!runsAgents(profile)) {
        setFailure(agents("notAChatModel"));
        return;
      }
      onCreated(profile);
    } catch (error) {
      setFailure(getErrorMessage(error, errors));
    } finally {
      onPendingChange?.(false);
    }
  };
  return (
    <div className="space-y-3" data-tour="model-subscription-connect">
      <p className="text-muted-foreground text-xs">{t("subscriptionHint")}</p>
      {actions.accounts.data?.enabled === false ? (
        <p role="status" className="text-sm">
          {t("unavailable")}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div role="status" className="flex flex-wrap items-center gap-2 text-xs">
              {connected ? (
                <>
                  <Badge variant="success" className="gap-1.5">
                    <CircleCheck aria-hidden className="size-3.5" />
                    {t("connected")}
                  </Badge>
                  {own
                    .filter(
                      (account) =>
                        !account.disabled &&
                        !account.unavailable &&
                        (account.email || account.label),
                    )
                    .map((account) => (
                      <span key={account.name} className="text-muted-foreground">
                        {account.email ?? account.label}
                      </span>
                    ))}
                </>
              ) : actions.accounts.isLoading ? (
                t("loading")
              ) : own.length ? (
                t("reconnect")
              ) : (
                accountsCopy("notConnected")
              )}
            </div>
            <Button
              type="button"
              size="sm"
              variant={connected ? "link" : "outline"}
              className={connected ? "h-auto p-0 text-xs" : undefined}
              disabled={
                disabled || !actions.ready || actions.accounts.isLoading || !!actions.accounts.error
              }
              onClick={() => setConnecting(true)}
            >
              {connected
                ? accountsCopy("connectAnother")
                : own.length
                  ? t("reconnect")
                  : accountsCopy("connect")}
            </Button>
          </div>
          {listing.error ? (
            <ErrorState
              title={t("loadFailed")}
              cta={{ label: accountsCopy("retry"), onClick: () => void listing.refetch() }}
            />
          ) : (
            connected && (
              <>
                {!listing.loading && listing.models.length === 0 && (
                  <div role="status" className="space-y-2 text-xs">
                    <p>{t("noModels")}</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void listing.refetch()}
                    >
                      {accountsCopy("retry")}
                    </Button>
                  </div>
                )}
                <FormField htmlFor={id} label={t("model")}>
                  <ModelCombobox
                    id={id}
                    provider="subscription_accounts"
                    value={model}
                    onChange={setModel}
                    options={listing.models}
                    source="live"
                    loading={listing.loading}
                    disabled={disabled || listing.loading}
                    placeholder={t("chooseModel")}
                  />
                </FormField>
                <Button
                  type="button"
                  disabled={
                    disabled ||
                    createProfile.isPending ||
                    listing.loading ||
                    !listing.models.some((entry) => entry.id === model)
                  }
                  onClick={() => void choose()}
                >
                  {t("useModel")}
                </Button>
              </>
            )
          )}
        </>
      )}
      {failure && (
        <p role="alert" className="text-destructive text-xs">
          {failure}
        </p>
      )}
      {connecting && (
        <SubscriptionSignInDialog
          key={actions.scope}
          provider={provider}
          actions={actions}
          onClose={() => setConnecting(false)}
        />
      )}
    </div>
  );
}
