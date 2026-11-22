"use client";

import { useId, useState, type ComponentType } from "react";
import { ChevronDown } from "lucide-react";

import {
  AddModel,
  endpointProfileLabel,
  modelIdIsWellFormed,
  modelPlaceholder,
  placeholderWords,
} from "@/components/agents/add-model";
import { ModelConnectionIntro } from "@/components/agents/model-connection-intro";
import { ModelSourceSelect, modelSourceOptions } from "@/components/agents/model-source-select";
import {
  subscriptionBelongsTo,
  subscriptionChoice,
  subscriptionFromChoice,
  subscriptionLabelMatches,
  subscriptionProviderFor,
} from "@/lib/subscription-accounts-api";
import { subscriptionModelId } from "@/lib/subscription-model-id";
import { useSubscriptionAccounts } from "@/hooks/use-subscription-accounts";
import { SubscriptionModelForm } from "@/components/agents/subscription-model-form";
import { ChatModelPane, ChatModelLibrary, type ChatModelLibraryProps } from "./chat-model-library";
import { ModelCombobox } from "@/components/agents/model-combobox";
import { getErrorMessage } from "@/lib/api-error";
import { ModelIcon } from "@/components/icons/model-icon";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ModelProviderCredential } from "./model-provider-credential";
import {
  useModelProviders,
  usePermissions,
  useProviderModels,
  useSecretPurposes,
  useSecrets,
} from "@/hooks";
import { hasKey, modelName, runsAgents, usableForAgents } from "@/lib/model-profiles";
import type { PublishedModel } from "@/types/agents";
import { Perm } from "@/types/permissions";
import type { ModelProfile } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ChatModelPickerProps {
  compact?: boolean;
  presentation?: "form" | "library";
  /** Initial catalog when setup has no agent model or conversation override yet. */
  defaultProviderId?: string;
  /** A dedicated setup surface reuses selection/credential contracts for one provider. */
  providerView?: { id: string; component: ComponentType<ChatModelLibraryProps> };
  /** The model profile this conversation overrides to, or null for the agent's own. */
  value: string | null;
  /** The agent's published model, shown as the current one when there is no override. */
  agentModel: PublishedModel | null;
  onChange: (profileId: string | null) => void;
}

/**
 * Which model this conversation runs on, chosen the way the Builder chooses one:
 * provider first, then the model - picked from that provider's published list or
 * typed as a free id, because providers ship models faster than any list here is
 * refreshed.
 *
 * The override the backend accepts is a model profile, so a choice that matches
 * one of the organization's profiles reuses it, and a new combination creates
 * one on the provider's vault key. A provider with no key in the vault cannot
 * answer, and the refusal says so here rather than after the first message.
 *
 * **It checks `connections:manage` over the fields, not over the whole panel.**
 * Creating a profile is `POST /providers/model-profiles`, gated on
 * `Perm.CONNECTIONS_MANAGE` and nothing else, while opening a conversation is
 * `agents:run` - so anybody who could type a message was offered these fields and
 * refused by the API after filling them in (#419). The gate covers the fields and
 * not only the submit, which is what #329 decided for the Builder's copy: three
 * fields that lead nowhere are worse than none.
 *
 * But reading which model the conversation runs on is `agents:view`, not that
 * permission's business, and the person who may not change it is the one most
 * likely to want to know (#926) - so the current-model summary renders above the
 * gate, and only the fields that write are withheld.
 */
export function ChatModelPicker({
  value,
  agentModel,
  onChange,
  compact = false,
  presentation = "form",
  defaultProviderId = "",
  providerView,
}: ChatModelPickerProps) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat.modelPicker");
  // Root, for the absolute keys `modelPlaceholder` answers with. Resolving them
  // through `t` above asked for `chat.modelPicker.pickProviderFirst`, which does
  // not exist - the copy lives under `agents`, where the Builder's form reads it.
  const tRoot = useTranslations();
  const { can } = usePermissions();
  const {
    profiles,
    catalog = [],
    createProfile,
    isLoading: loadingProfiles,
    profilesStatus,
    refetchProfiles,
  } = useModelProviders({ silentCreate: true });
  const { purposes, isLoading: loadingPurposes } = useSecretPurposes();
  const {
    secrets,
    listError: secretReadError,
    isLoading: loadingSecrets,
    refetch: refetchSecrets,
  } = useSecrets();

  const current = value === null ? agentModel : (profiles.find((p) => p.id === value) ?? null);
  const currentProfile = profiles.find(
    (profile) => profile.id === (value ?? agentModel?.profile_id),
  );
  const sourceKey = value ?? "agent";
  const [draft, setDraft] = useState<{
    source: string;
    providerId: string;
    model: string;
  } | null>(null);
  const edited = draft?.source === sourceKey ? draft : null;
  const personalAccounts = useSubscriptionAccounts({
    enabled:
      !providerView &&
      (current?.provider === "subscription_accounts" ||
        catalog.some((entry) => entry.personal_gateway)),
  });
  const currentSubscription = subscriptionProviderFor(
    current,
    personalAccounts.accounts.data?.items ?? [],
    (provider) => tRoot(`subscriptionAccounts.providers.${provider}`),
  );
  const currentSource = currentSubscription
    ? subscriptionChoice(currentSubscription)
    : current?.provider === "subscription_accounts"
      ? ""
      : current?.provider;
  const providerId = providerView?.id ?? edited?.providerId ?? currentSource ?? defaultProviderId;
  const subscription = subscriptionFromChoice(providerId);
  const personalSource = subscription !== undefined || providerId === "subscription_accounts";
  const model = edited?.model ?? current?.model ?? "";
  const setProviderId = (next: string) =>
    setDraft({ source: sourceKey, providerId: next, model: "" });
  const setModel = (next: string) => setDraft({ source: sourceKey, providerId, model: next });
  const [failure, setFailure] = useState<string | null>(null);

  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const providerKeys = secrets.filter((secret) => secret.purpose === providerId);
  const explicitKey = providerKeys.find((secret) => secret.id === pickedKey);
  const inheritedProfile = currentProfile?.provider === providerId ? currentProfile : undefined;
  const effectiveKey =
    explicitKey ??
    providerKeys.find((key) => key.id === inheritedProfile?.secret_id) ??
    providerKeys[0];
  const matchesKey = (profile: ModelProfile) =>
    !effectiveKey || profile.secret_id === effectiveKey.id;
  const [pickedEndpoint, setPickedEndpoint] = useState<{
    source: string;
    value: string | null;
  } | null>(null);
  const endpoint =
    providerId === "openrouter" && pickedEndpoint?.source === sourceKey
      ? pickedEndpoint.value
      : (inheritedProfile?.base_url ?? null);
  const globalEndpoint = "https://openrouter.ai/api/v1";
  const euEndpoint = "https://eu.openrouter.ai/api/v1";
  const endpointIdentity = (value: string | null | undefined) =>
    value?.replace(/\/+$/, "") || globalEndpoint;
  const matchesEndpoint = (profile: Pick<ModelProfile, "base_url">) =>
    providerId === "openrouter" && pickedEndpoint?.source === sourceKey
      ? endpointIdentity(profile.base_url) === endpointIdentity(endpoint)
      : !endpoint || profile.base_url?.replace(/\/+$/, "") === endpoint.replace(/\/+$/, "");
  const currentEndpointMatches = currentProfile ? matchesEndpoint(currentProfile) : !endpoint;
  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  const requiresEndpoint = catalog.some(
    (entry) => entry.id === providerId && entry.requires_base_url,
  );
  const {
    models: suggestions,
    refused,
    source,
    isLoading: loadingModels,
    hasCachedListing,
    refetch: refetchModels,
    error: catalogError,
    canRefresh,
  } = useProviderModels(
    subscription ? "" : providerId,
    providerId === "openrouter" ? (endpoint ?? undefined) : undefined,
    effectiveKey?.id,
  );
  // An override profile and the agent's published model both carry
  // provider/model/label, so one summary renders whichever is current.

  const matching = profiles.filter(
    (profile) =>
      profile.provider === providerId &&
      profile.model === model.trim() &&
      (providerId !== "openai_chatgpt" || profile.secret_id === effectiveKey?.id) &&
      matchesEndpoint(profile),
  );
  const hasCustomEndpoint = matching.some(
    (profile) => matchesKey(profile) && !!profile.base_url && usableForAgents(profile),
  );

  const canApply =
    provider !== undefined &&
    model.trim() !== "" &&
    modelIdIsWellFormed(provider.id, model.trim()) &&
    !createProfile.isPending &&
    !loadingProfiles &&
    profilesStatus !== "failed" &&
    !loadingSecrets &&
    !secretReadError &&
    (!loadingModels || hasCustomEndpoint);

  const apply = async (selectedModel = model) => {
    if (
      provider === undefined ||
      createProfile.isPending ||
      loadingProfiles ||
      profilesStatus === "failed" ||
      loadingSecrets ||
      secretReadError
    )
      return;
    const modelId = selectedModel.trim();
    if (!modelIdIsWellFormed(provider.id, modelId)) return;
    const matching = profiles.filter(
      (profile) =>
        profile.provider === providerId && profile.model === modelId && matchesEndpoint(profile),
    );
    if (
      loadingModels &&
      !matching.some(
        (profile) => matchesKey(profile) && profile.base_url && usableForAgents(profile),
      )
    )
      return;
    setFailure(null);
    if (
      current?.provider === provider.id &&
      current.model === modelId &&
      currentEndpointMatches &&
      (!currentProfile || matchesKey(currentProfile)) &&
      (currentProfile === undefined || usableForAgents(currentProfile))
    ) {
      onChange(value);
      return;
    }

    // The organization may already have this exact model as a profile - reuse
    // it rather than minting a duplicate row per conversation.
    // Several profiles can name the same vendor/model. Prefer one that can
    // chat, including a custom endpoint whose names the vendor cannot classify.
    const listingRefuses = refused.includes(modelId);
    const existing = matching.find(
      (profile) =>
        matchesKey(profile) &&
        usableForAgents(profile) &&
        (!!profile.base_url || (!loadingModels && !listingRefuses)),
    );
    if (existing) {
      onChange(existing.id);
      return;
    }
    // The organization has this model, but its key was deleted (#2478). A second
    // profile under the same name is refused, and the fix is a key for this one.
    if (
      providerKeys.length <= 1 &&
      !listingRefuses &&
      matching.some((profile) => runsAgents(profile) && !hasKey(profile))
    ) {
      setFailure(t("modelHasNoKey", { model: modelId }));
      return;
    }
    if (matching.some(matchesKey) || listingRefuses) {
      setFailure(t("notAChatModel", { model: modelId }));
      return;
    }

    const key = effectiveKey;
    if (key === undefined) {
      // The form below offers to add one, so this says what is missing rather than
      // sending somebody to another page for it.
      setFailure(t("noProviderKey", { provider: provider.label }));
      return;
    }

    try {
      const baseLabel =
        providerKeys.length > 1
          ? `${`${provider.label} · ${modelId}`.slice(0, 108)} · ${key.id.slice(0, 8)}`
          : `${provider.label} · ${modelId}`;
      const profile = await createProfile.mutateAsync({
        label: profiles.some((profile) => profile.label === baseLabel)
          ? endpointProfileLabel(
              baseLabel,
              endpoint ?? "",
              profiles.map((profile) => profile.label),
              globalEndpoint,
            )
          : baseLabel,
        provider: provider.id,
        model: modelId,
        secret_id: key.id,
        ...(endpoint ? { base_url: endpoint } : {}),
        ...(inheritedProfile?.api ? { api: inheritedProfile.api } : {}),
      });
      // An id the listing did not classify still reaches here: the server
      // classifies the new profile, and a conversation cannot run on it either.
      if (!runsAgents(profile)) {
        setFailure(t("notAChatModel", { model: modelId }));
        return;
      }
      onChange(profile.id);
    } catch (error) {
      // Caught, not left to reject: every refusal this endpoint gives is about
      // the model id, so it belongs under the field, where it can be fixed.
      setFailure(getErrorMessage(error, tErrors));
    }
  };

  const credentialForm = !secretReadError &&
    !loadingSecrets &&
    provider !== undefined &&
    (providerView || !secrets.some((secret) => secret.purpose === provider.id)) && (
      <ModelProviderCredential
        key={provider.id}
        provider={provider}
        onCreated={() => {
          setFailure(null);
          void refetchModels();
        }}
      />
    );

  const currentSummary = current ? (
    <>
      <ModelIcon model={current.model} provider={current.provider} />
      <span className="min-w-0 flex-1">
        <span
          className={
            compact
              ? "block truncate text-xs font-medium"
              : "block text-sm leading-5 font-medium break-words whitespace-normal"
          }
        >
          {modelName(
            current,
            current.provider === providerId
              ? suggestions.find((entry) => entry.id === current.model)?.name
              : undefined,
          )}
        </span>
      </span>
    </>
  ) : (
    t("changeModel")
  );

  const catalogConnection =
    providerId === "openrouter" ? (
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor={`${panelId}-catalog-region`}>{t("catalogRegion")}</Label>
          <Select
            value={endpointIdentity(endpoint)}
            onValueChange={(next) => {
              setPickedEndpoint({
                source: sourceKey,
                value: next === globalEndpoint ? null : next,
              });
              setFailure(null);
            }}
          >
            <SelectTrigger id={`${panelId}-catalog-region`} className="h-8 w-auto min-w-32 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={globalEndpoint}>{t("catalogGlobal")}</SelectItem>
              <SelectItem value={euEndpoint}>{t("catalogEu")}</SelectItem>
              {![globalEndpoint, euEndpoint].includes(endpointIdentity(endpoint)) && (
                <SelectItem value={endpointIdentity(endpoint)}>{t("catalogCustom")}</SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
        <p className="text-muted-foreground text-xs">{t("catalogRegionHint")}</p>
      </div>
    ) : undefined;

  const sourceProfiles = profiles.filter((profile) => {
    const provider = subscription ? "subscription_accounts" : providerId;
    if (
      profile.provider !== provider ||
      !usableForAgents(profile) ||
      (!requiresEndpoint && !matchesKey(profile))
    )
      return false;
    if (profile.provider !== "subscription_accounts") return true;
    if (subscriptionModelId(profile.model) !== profile.model) {
      return (personalAccounts.accounts.data?.items ?? []).some(
        (account) =>
          account.model_prefix &&
          profile.model.startsWith(account.model_prefix + "/") &&
          !account.disabled &&
          !account.unavailable &&
          (!subscription || subscriptionBelongsTo(account, subscription)),
      );
    }
    return (
      !subscription ||
      subscriptionLabelMatches(
        profile.label,
        subscription,
        tRoot(`subscriptionAccounts.providers.${subscription}`),
      )
    );
  });

  const connectionUnavailable =
    loadingProfiles ||
    profilesStatus === "failed" ||
    (!personalSource && (!!secretReadError || !!loadingSecrets));
  const endpointForm =
    (requiresEndpoint || personalSource) && !connectionUnavailable ? (
      <div className="space-y-3">
        {profiles.some(
          (profile) => profile.provider === providerId && usableForAgents(profile),
        ) && (
          <div
            role="group"
            aria-label={t(presentation === "library" ? "allModels" : "savedModels")}
            className="grid gap-2"
          >
            <p className="text-muted-foreground text-xs">
              {t(presentation === "library" ? "allModels" : "savedModels")}
            </p>
            {profiles
              .filter((profile) => profile.provider === providerId && usableForAgents(profile))
              .map((profile) => (
                <Button
                  key={profile.id}
                  type="button"
                  variant="outline"
                  className="h-auto min-h-10 justify-start text-left whitespace-normal"
                  onClick={() => onChange(profile.id)}
                >
                  {modelName(profile)}
                </Button>
              ))}
          </div>
        )}
        <AddModel
          key={providerId}
          fixedProviderId={providerId}
          presentation={presentation}
          selected={personalSource && currentSource === providerId ? currentProfile : undefined}
          purpose="chat"
          onCreated={(profile) => onChange(profile.id)}
        />
      </div>
    ) : null;

  const credentialPicker = !requiresEndpoint && providerKeys.length > 1 && (
    <div className="grid gap-1.5">
      <Label htmlFor="chat-model-key">{tRoot("vault.key")}</Label>
      <Select value={effectiveKey?.id} onValueChange={setPickedKey}>
        <SelectTrigger id="chat-model-key">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {providerKeys.map((key) => (
            <SelectItem key={key.id} value={key.id} textValue={key.name}>
              <ProviderRow provider={providerId} name={key.name} hint={key.hint} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  const Library = providerView?.component ?? ChatModelLibrary;
  if (presentation === "library" && can(Perm.connectionsManage))
    return (
      <Library
        pane={
          subscription ? (
            <SubscriptionModelForm
              key={providerId}
              provider={subscription}
              initialModel={currentSource === providerId ? current?.model : undefined}
              disabled={connectionUnavailable}
              onCreated={(profile) => onChange(profile.id)}
              libraryPane={ChatModelPane}
            />
          ) : undefined
        }
        providers={modelSourceOptions(
          providers,
          catalog.some((entry) => entry.personal_gateway),
          tRoot,
        ).map((entry) => ({
          ...entry,
          connected:
            entry.group === "subscriptions"
              ? personalAccounts.accounts.data
                ? personalAccounts.accounts.data.items.some((account) => {
                    const provider = subscriptionFromChoice(entry.id);
                    return (
                      provider !== undefined &&
                      subscriptionBelongsTo(account, provider) &&
                      !account.disabled &&
                      !account.unavailable
                    );
                  })
                : null
              : secretReadError || loadingSecrets
                ? null
                : secrets.some((secret) => secret.purpose === entry.id) ||
                  profiles.some(
                    (profile) => profile.provider === entry.id && usableForAgents(profile),
                  ),
        }))}
        providerId={providerId}
        connectionLabel={providerView ? effectiveKey?.name : undefined}
        catalogConnection={catalogConnection}
        catalogSource={source}
        catalogError={!!catalogError}
        onRefresh={
          canRefresh && !personalSource && !requiresEndpoint
            ? () => void refetchModels()
            : undefined
        }
        loadingProviders={loadingPurposes}
        configurationForm={endpointForm}
        needsCredential={
          !requiresEndpoint &&
          !!credentialForm &&
          providerKeys.length === 0 &&
          !profiles.some((profile) => profile.provider === providerId && usableForAgents(profile))
        }
        credentialPicker={credentialPicker}
        model={
          current?.provider === providerId &&
          currentEndpointMatches &&
          (!currentProfile || matchesKey(currentProfile))
            ? current.model
            : ""
        }
        models={suggestions}
        profiles={sourceProfiles}
        catalogProfiles={sourceProfiles.filter(matchesEndpoint)}
        loading={(loadingModels && !hasCachedListing) || loadingProfiles}
        catalogRefreshing={loadingModels}
        applying={createProfile.isPending}
        disabled={connectionUnavailable}
        onProviderChange={(id) => {
          setProviderId(id);
          setPickedKey(null);
          setFailure(null);
        }}
        onModelChange={(id) => void apply(id)}
        credentialForm={
          requiresEndpoint ? null : providerView ? (
            credentialForm
          ) : credentialForm && provider ? (
            <ModelConnectionIntro provider={provider.id} name={provider.label}>
              {credentialForm}
            </ModelConnectionIntro>
          ) : null
        }
        failure={
          profilesStatus === "failed" || (!personalSource && secretReadError) ? (
            <p role="alert" className="text-destructive text-xs">
              {t("profilesUnavailable")}{" "}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void refetchProfiles();
                  void refetchSecrets();
                }}
              >
                {tRoot("common.retry")}
              </Button>
            </p>
          ) : failure ? (
            <p role="alert" className="text-destructive text-xs">
              {failure}
            </p>
          ) : null
        }
      />
    );

  return (
    <div className="space-y-4">
      {current && !can(Perm.connectionsManage) && (
        <p
          data-tour="chat-model-picker"
          className="bg-background/60 flex items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-xs"
        >
          {currentSummary}
          <span className="text-muted-foreground shrink-0 text-[11px]">
            {value === null ? t("agentModel") : t("thisChat")}
          </span>
        </p>
      )}

      {!can(Perm.connectionsManage) ? (
        <p className="text-muted-foreground text-xs">{t("needsConnectionsManage")}</p>
      ) : (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={
              compact
                ? "h-auto min-h-10 w-full justify-start gap-2 rounded-lg px-2 py-2 text-left text-xs"
                : "h-auto min-h-16 w-full items-start justify-start gap-3 rounded-xl px-3.5 py-3 text-left text-[13px]"
            }
            aria-label={t("changeModel")}
            data-tour="chat-model-picker"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => setExpanded((open) => !open)}
          >
            {currentSummary}
            <span className="text-muted-foreground mt-0.5 shrink-0 text-[11px]">
              {value === null ? t("agentModel") : t("thisChat")}
            </span>
            <ChevronDown
              aria-hidden
              className={`mt-1 h-3.5 w-3.5 shrink-0 transition-transform motion-reduce:transition-none ${expanded ? "rotate-180" : ""}`}
            />
          </Button>
          {expanded && (
            <div
              id={panelId}
              className="animate-in fade-in space-y-4 pt-5 duration-150 motion-reduce:animate-none"
            >
              {(profilesStatus === "failed" || (!personalSource && secretReadError)) && (
                <p role="alert" className="text-destructive text-xs">
                  {t("profilesUnavailable")}{" "}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      void refetchProfiles();
                      void refetchSecrets();
                    }}
                  >
                    {tRoot("common.retry")}
                  </Button>
                </p>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="chat-model-provider">{t("provider")}</Label>
                <ModelSourceSelect
                  id="chat-model-provider"
                  value={providerId}
                  providers={providers}
                  subscriptions={catalog.some((entry) => entry.personal_gateway)}
                  onChange={(next) => {
                    setProviderId(next);
                    setFailure(null);
                  }}
                />
              </div>

              {requiresEndpoint ||
              subscription !== undefined ||
              providerId === "subscription_accounts" ? (
                endpointForm
              ) : (
                <>
                  {catalogConnection}
                  {credentialPicker}
                  <div className="space-y-1.5">
                    <Label htmlFor="chat-model-id">{t("model")}</Label>
                    {/* The Builder's own picker: the provider's catalog, searchable, and
                still able to carry an id that is not in it. */}
                    <ModelCombobox
                      provider={provider?.id}
                      id="chat-model-id"
                      value={model}
                      onChange={(next) => {
                        setModel(next);
                        setFailure(null);
                      }}
                      options={suggestions}
                      source={source}
                      onRefresh={canRefresh ? () => void refetchModels() : undefined}
                      loading={loadingModels}
                      disabled={provider === undefined}
                      placeholder={placeholderWords(modelPlaceholder(provider?.id), tRoot)}
                    />
                    {catalogError && (
                      <p role="alert" className="text-destructive text-xs">
                        {t("catalogFailed")}
                      </p>
                    )}
                    {failure !== null && <p className="text-destructive text-xs">{failure}</p>}
                  </div>

                  {/* A key can be added here rather than on another page. A picker that can
              only offer what is already stored, and answers "add one in the Vault"
              when nothing is, is a dead end - and the provider is already chosen, so
              the purpose this key needs is known. */}
                  {credentialForm}

                  <Button
                    type="button"
                    className="w-full"
                    disabled={!canApply}
                    onClick={() => void apply()}
                  >
                    {t("runModel")}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
