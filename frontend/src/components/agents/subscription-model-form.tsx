"use client";

import {
  useId,
  useState,
  useRef,
  useLayoutEffect,
  type ComponentType,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { CircleCheck } from "lucide-react";
import {
  Badge,
  Button,
  FormField,
  Spinner,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { ModelCombobox } from "./model-combobox";
import { SubscriptionAccountUsage } from "./subscription-account-usage";
import { SubscriptionSignInDialog } from "@/components/settings/subscription-accounts";
import { ModelConnectionIntro } from "./model-connection-intro";
import { ProviderRow } from "@/components/vault/provider-row";
import { useSubscriptionAccounts, useSubscriptionModels } from "@/hooks/use-subscription-accounts";
import { useModelProviders } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { runsAgents } from "@/lib/model-profiles";
import {
  SUBSCRIPTION_MARK,
  subscriptionBelongsTo,
  subscriptionLabelMatches,
  type SubscriptionProvider,
  type SubscriptionAccount,
} from "@/lib/subscription-accounts-api";
import { subscriptionModelId } from "@/lib/subscription-model-id";
import type { ChatModelPaneProps } from "@/components/chat/chat-model-library";
import type { ModelProfile } from "@/types/providers";

/** A selected account supplies models to AgenticOS, independently of coding harnesses. */
export function SubscriptionModelForm({
  provider,
  initialModel = "",
  onCreated,
  disabled,
  onPendingChange,
  libraryPane: LibraryPane,
  providerField,
}: {
  provider: SubscriptionProvider;
  initialModel?: string;
  onCreated: (profile: ModelProfile) => void;
  disabled?: boolean;
  onPendingChange?: (pending: boolean) => void;
  libraryPane?: ComponentType<ChatModelPaneProps>;
  providerField?: ReactNode;
}) {
  const t = useTranslations("modelSources");
  const chatCopy = useTranslations("chat.modelPicker");
  const accountsCopy = useTranslations("subscriptionAccounts");
  const errors = useTranslations("errors");
  const agents = useTranslations("agents");
  const id = useId();
  const actions = useSubscriptionAccounts();
  const { createProfile, profiles } = useModelProviders({ silentCreate: true });
  const [connecting, setConnecting] = useState(false);
  const [pickedAccount, setPickedAccount] = useState<string | null>(null);
  const [model, setModel] = useState(subscriptionModelId(initialModel));
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
  const available = own.filter((account) => !account.disabled && !account.unavailable);
  const account =
    available.find((entry) => entry.name === pickedAccount) ??
    available.find(
      (entry) => entry.model_prefix && initialModel.startsWith(entry.model_prefix + "/"),
    ) ??
    available[0];
  const connected = account !== undefined;
  const listing = useSubscriptionModels(provider, account?.name);
  const pending = actions.selectModel.isPending || createProfile.isPending;
  const identity = (entry: (typeof own)[number], index: number) =>
    entry.email || entry.label || t("accountNumber", { number: index + 1 });

  const choose = async (selectedAccount: SubscriptionAccount, selectedModel: string) => {
    onPendingChange?.(true);
    setFailure(null);
    try {
      const selected = await actions.selectModel.mutateAsync({
        name: selectedAccount.name,
        model: selectedModel,
      });
      if (!active.current || !actions.isCurrentScope()) return;
      const existing = profiles.find(
        (entry) =>
          entry.provider === "subscription_accounts" &&
          entry.model === selected.model &&
          runsAgents(entry),
      );
      const profile =
        existing ??
        (await createProfile.mutateAsync({
          provider: "subscription_accounts",
          model: selected.model,
          secret_id: null,
          label: `${accountsCopy(`providers.${provider}`)} · ${selected.model}`.slice(0, 128),
        }));
      if (!active.current || !actions.isCurrentScope()) return;
      if (!runsAgents(profile)) {
        setFailure(agents("notAChatModel"));
        return;
      }
      setModel(selectedModel);
      onCreated(profile);
    } catch (error) {
      if (active.current && actions.isCurrentScope()) setFailure(getErrorMessage(error, errors));
    } finally {
      onPendingChange?.(false);
    }
  };
  const accountSettings = (
    <>
      <div className="space-y-3">
        {own.length > 1 && (
          <FormField htmlFor={`${id}-account`} label={t("account")}>
            <Select
              value={account?.name ?? ""}
              disabled={disabled || pending}
              onValueChange={(next) => {
                setPickedAccount(next);
                setModel("");
                setFailure(null);
              }}
            >
              <SelectTrigger id={`${id}-account`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {own.map((entry, index) => (
                  <SelectItem
                    key={entry.name}
                    value={entry.name}
                    disabled={entry.disabled || entry.unavailable}
                    textValue={identity(entry, index)}
                  >
                    <ProviderRow
                      provider={SUBSCRIPTION_MARK[provider]}
                      name={identity(entry, index)}
                    />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <div role="status" className="flex flex-wrap items-center gap-2 text-xs">
            {actions.accounts.data?.enabled === false ? (
              t("unavailable")
            ) : connected ? (
              <>
                <Badge variant="success" className="gap-1.5">
                  <CircleCheck aria-hidden className="size-3.5" />
                  {t("connected")}
                </Badge>
                {own.length === 1 && (
                  <span className="text-muted-foreground">{identity(account, 0)}</span>
                )}
              </>
            ) : actions.accounts.isLoading ? (
              t("loading")
            ) : own.length ? (
              t("reconnect")
            ) : (
              accountsCopy("notConnected")
            )}
          </div>
          {actions.accounts.data?.enabled !== false && (
            <Button
              type="button"
              size="sm"
              variant={connected ? "link" : "outline"}
              className={connected ? "h-auto p-0 text-xs" : undefined}
              disabled={
                disabled ||
                pending ||
                !actions.ready ||
                actions.accounts.isLoading ||
                !!actions.accounts.error
              }
              onClick={() => setConnecting(true)}
            >
              {connected
                ? accountsCopy("connectAnother")
                : own.length
                  ? t("reconnect")
                  : accountsCopy("connect")}
            </Button>
          )}
        </div>
        {own.map((entry, index) => (
          <div key={entry.name} className="border-border space-y-2 border-t pt-3">
            {own.length > 1 && <p className="text-xs font-medium">{identity(entry, index)}</p>}
            <SubscriptionAccountUsage account={entry} />
          </div>
        ))}
        <p className="text-muted-foreground text-xs">{t("subscriptionHint")}</p>
      </div>
      {connecting && (
        <SubscriptionSignInDialog
          key={actions.scope}
          provider={provider}
          actions={actions}
          onClose={() => setConnecting(false)}
        />
      )}
    </>
  );
  if (LibraryPane) {
    const accountProfiles = profiles.filter(
      (entry) =>
        entry.provider === "subscription_accounts" &&
        account &&
        (account.model_prefix
          ? entry.model.startsWith(account.model_prefix + "/")
          : subscriptionLabelMatches(entry.label, provider, accountsCopy(`providers.${provider}`))),
    );
    const paneProps: ChatModelPaneProps = {
      providerId: "subscription_accounts",
      model,
      models: listing.models,
      profiles: accountProfiles,
      catalogProfiles: [],
      loading: actions.accounts.isLoading || listing.loading,
      catalogSource: "live",
      catalogError: !!listing.error || !!actions.accounts.error,
      allowCustom: false,
      onRefresh: () => void listing.refetch(),
      credentialTabLabel: t("account"),
      connectionLabel: account ? identity(account, own.indexOf(account)) : undefined,
      needsCredential: !connected && !actions.accounts.isLoading,
      credentialPicker: connected ? accountSettings : null,
      credentialForm: connected ? null : (
        <ModelConnectionIntro
          provider={SUBSCRIPTION_MARK[provider]}
          name={accountsCopy(`providers.${provider}`)}
          description={t("subscriptionHint")}
        >
          {actions.accounts.error ? (
            <ErrorState
              title={accountsCopy("loadFailed")}
              cta={{ label: accountsCopy("retry"), onClick: () => void actions.accounts.refetch() }}
            />
          ) : (
            <Button
              type="button"
              disabled={!actions.ready || actions.accounts.data?.enabled === false}
              onClick={() => setConnecting(true)}
            >
              {accountsCopy("connect")}
            </Button>
          )}
          {connecting && (
            <SubscriptionSignInDialog
              key={actions.scope}
              provider={provider}
              actions={actions}
              onClose={() => setConnecting(false)}
            />
          )}
        </ModelConnectionIntro>
      ),
      applying: pending,
      disabled: !!disabled || !!listing.error || !connected,
      onModelChange: (next) => {
        if (account) void choose(account, next);
      },
      failure: failure ? (
        <p role="alert" className="text-destructive text-xs">
          {failure}
        </p>
      ) : null,
    };
    return <LibraryPane {...paneProps} />;
  }
  return (
    <div className="space-y-4" data-tour="model-subscription-connect">
      <div
        className={
          providerField ? "grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]" : undefined
        }
      >
        {providerField}
        <FormField htmlFor={id} label={t("model")}>
          <ModelCombobox
            id={id}
            provider="subscription_accounts"
            value={model}
            allowCustom={false}
            onChange={(next) => {
              if (account) void choose(account, next);
            }}
            options={listing.models}
            source="live"
            onRefresh={() => void listing.refetch()}
            loading={listing.loading}
            disabled={
              disabled ||
              pending ||
              listing.loading ||
              !connected ||
              !!listing.error ||
              listing.models.length === 0
            }
            placeholder={t("chooseModel")}
          />
        </FormField>
      </div>
      {listing.error ? (
        <ErrorState
          title={t("loadFailed")}
          cta={{ label: accountsCopy("retry"), onClick: () => void listing.refetch() }}
        />
      ) : connected && !listing.loading && listing.models.length === 0 ? (
        <div role="status" className="space-y-2 text-xs">
          <p>{t("noModels")}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => void listing.refetch()}>
            {accountsCopy("retry")}
          </Button>
        </div>
      ) : null}
      {pending && (
        <p role="status" className="text-muted-foreground flex items-center gap-2 text-xs">
          <Spinner className="size-3.5" />
          {chatCopy("applyingModel")}
        </p>
      )}
      {failure && (
        <p role="alert" className="text-destructive text-xs">
          {failure}
        </p>
      )}
      <div className="border-border border-t pt-3">{accountSettings}</div>
    </div>
  );
}
