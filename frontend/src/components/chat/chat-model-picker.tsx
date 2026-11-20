"use client";

import { useId, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

import {
  modelIdIsWellFormed,
  modelPlaceholder,
  placeholderWords,
} from "@/components/agents/add-model";
import { ModelCombobox } from "@/components/agents/model-combobox";
import { ClaudeSubscriptionModelSelect } from "@/components/chat/claude-subscription-model-select";
import { getErrorMessage } from "@/lib/api-error";
import { ProviderIcon } from "@/components/vault/provider-icon";
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
import { InlineChatGPTSignIn } from "@/components/vault/chatgpt-sign-in";
import { InlineSecret } from "@/components/vault/inline-secret";
import { PersonalApiConnection } from "@/components/vault/personal-api-connection";
import {
  useModelProviders,
  usePermissions,
  useProviderModels,
  useSecretPurposes,
  useSecrets,
} from "@/hooks";
import {
  connectionModelLabel,
  hasKey,
  modelDetail,
  runsAgents,
  usableForAgents,
} from "@/lib/model-profiles";
import type { PublishedModel } from "@/types/agents";
import type { Secret } from "@/types/secrets";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface ChatModelPickerProps {
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
export function ChatModelPicker({ value, agentModel, onChange }: ChatModelPickerProps) {
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
    createProfile,
    isLoading: loadingProfiles,
    profilesStatus,
    refetchProfiles,
  } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();

  const current = value === null ? agentModel : (profiles.find((p) => p.id === value) ?? null);
  const currentProfile = profiles.find(
    (profile) => profile.id === (value ?? agentModel?.profile_id),
  );
  const sourceKey = value ?? "agent";
  const [draft, setDraft] = useState<{
    source: string;
    providerId: string;
    model: string;
    secretId: string | null;
  } | null>(null);
  const [createdConnection, setCreatedConnection] = useState<Secret | null>(null);
  const edited = draft?.source === sourceKey ? draft : null;
  const providerId = edited?.providerId ?? current?.provider ?? "";
  const model = edited?.model ?? current?.model ?? "";
  const setProviderId = (next: string) =>
    setDraft({ source: sourceKey, providerId: next, model: "", secretId: null });
  const setModel = (next: string) =>
    setDraft({ source: sourceKey, providerId, model: next, secretId: edited?.secretId ?? null });
  const [failure, setFailure] = useState<string | null>(null);
  const chooseConnection = (id: string) => {
    setDraft({ source: sourceKey, providerId, model, secretId: id });
    setFailure(null);
  };

  const inheritedProfile = currentProfile?.provider === providerId ? currentProfile : undefined;
  const availableSecrets =
    createdConnection && !secrets.some((secret) => secret.id === createdConnection.id)
      ? [...secrets, createdConnection]
      : secrets;
  const keys = availableSecrets.filter((secret) => secret.purpose === providerId);
  const chosenSecretId =
    edited?.secretId ??
    (inheritedProfile ? inheritedProfile.secret_id : keys.length === 1 ? keys[0]!.id : null);
  const key = keys.find((secret) => secret.id === chosenSecretId);
  const personal = key?.usage_scope === "personal";
  // A new personal connection starts on the provider's API, not an inherited gateway.
  const endpoint =
    personal && chosenSecretId !== inheritedProfile?.secret_id
      ? null
      : (inheritedProfile?.base_url ?? null);
  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  const {
    models: suggestions,
    refused,
    source,
    isLoading: loadingModels,
  } = useProviderModels(
    providerId === "claude-subscription" || (personal && endpoint) ? "" : providerId,
    providerId === "openrouter" ? (endpoint ?? undefined) : undefined,
    personal && !endpoint ? (chosenSecretId ?? undefined) : undefined,
  );
  // An override profile and the agent's published model both carry
  // provider/model/label, so one summary renders whichever is current.
  const currentDetail = current ? modelDetail(current) : null;

  const matching = profiles.filter(
    (profile) =>
      profile.provider === providerId &&
      profile.model === model.trim() &&
      (chosenSecretId !== null
        ? profile.secret_id === chosenSecretId
        : inheritedProfile?.usage_scope === "personal"
          ? profile.id === inheritedProfile.id
          : profile.usage_scope !== "personal") &&
      (!(personal && chosenSecretId !== inheritedProfile?.secret_id) || !profile.base_url) &&
      (!endpoint || profile.base_url?.replace(/\/+$/, "") === endpoint.replace(/\/+$/, "")),
  );
  const hasCustomEndpoint = matching.some(
    (profile) => !!profile.base_url && usableForAgents(profile),
  );

  const canApply =
    provider !== undefined &&
    model.trim() !== "" &&
    modelIdIsWellFormed(provider.id, model.trim()) &&
    !createProfile.isPending &&
    !loadingProfiles &&
    profilesStatus !== "failed" &&
    (keys.length <= 1 || chosenSecretId !== null) &&
    (!loadingModels || hasCustomEndpoint);

  const apply = async () => {
    if (provider === undefined) return;
    const modelId = model.trim();
    setFailure(null);
    if (
      current?.provider === provider.id &&
      current.model === modelId &&
      (currentProfile ? currentProfile.secret_id === chosenSecretId : chosenSecretId === null) &&
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
    const usable = matching.filter(
      (profile) =>
        usableForAgents(profile) && (!!profile.base_url || (!loadingModels && !listingRefuses)),
    );
    // Different connection IDs are a billing choice; an array's order cannot decide it.
    if (new Set(usable.map((profile) => profile.secret_id)).size > 1) {
      setFailure(tRoot("personalModels.chooseConnection"));
      return;
    }
    const existing = usable[0];
    if (existing) {
      onChange(existing.id);
      return;
    }
    // The organization has this model, but its key was deleted (#2478). A second
    // profile under the same name is refused, and the fix is a key for this one.
    if (!listingRefuses && matching.some((profile) => runsAgents(profile) && !hasKey(profile))) {
      setFailure(t("modelHasNoKey", { model: modelId }));
      return;
    }
    if (matching.length > 0 || listingRefuses) {
      setFailure(t("notAChatModel", { model: modelId }));
      return;
    }

    if (key === undefined) {
      // The form below offers to add one, so this says what is missing rather than
      // sending somebody to another page for it.
      setFailure(t("noProviderKey", { provider: provider.label }));
      return;
    }

    try {
      const baseLabel = `${provider.label} · ${modelId}`;
      const labels = profiles.map((profile) => profile.label);
      const profile = await createProfile.mutateAsync({
        label:
          personal || labels.includes(baseLabel)
            ? connectionModelLabel(baseLabel, key.name, labels)
            : baseLabel,
        provider: provider.id,
        model: modelId,
        secret_id: key.id,
        ...(endpoint ? { base_url: endpoint } : {}),
        ...(inheritedProfile?.api && (!personal || chosenSecretId === inheritedProfile.secret_id)
          ? { api: inheritedProfile.api }
          : {}),
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

  const currentSummary = current ? (
    <>
      <span className="bg-foreground/[0.05] text-foreground flex size-9 shrink-0 items-center justify-center rounded-lg">
        <ProviderIcon provider={current.provider} className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm leading-5 font-medium break-words whitespace-normal">
          {current.label}
        </span>
        {currentProfile?.usage_scope === "personal" && (
          <span className="text-muted-foreground text-xs">{tRoot("personalModels.personal")}</span>
        )}
        {currentDetail !== null && (
          <span className="text-muted-foreground mt-1 block truncate font-mono text-[11px]">
            {currentDetail}
          </span>
        )}
      </span>
    </>
  ) : (
    t("changeModel")
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
            className="h-auto min-h-16 w-full items-start justify-start gap-3 rounded-xl px-3.5 py-3 text-left text-[13px]"
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
              {profilesStatus === "failed" && (
                <p role="alert" className="text-destructive text-xs">
                  {t("profilesUnavailable")}{" "}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => void refetchProfiles()}
                  >
                    {tRoot("common.retry")}
                  </Button>
                </p>
              )}
              <ClaudeSubscriptionModelSelect
                profiles={profiles}
                value={currentProfile?.id ?? null}
                disabled={loadingProfiles || profilesStatus === "failed"}
                onChange={(profileId) => {
                  setFailure(null);
                  onChange(profileId);
                }}
              />
              {providerId === "claude-subscription" ? (
                <Button type="button" variant="outline" size="sm" onClick={() => setProviderId("")}>
                  {tRoot("claudeSubscription.chooseApiModel")}
                </Button>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="chat-model-provider">{t("provider")}</Label>
                    <Select
                      value={providerId}
                      onValueChange={(next) => {
                        setProviderId(next);
                        setFailure(null);
                      }}
                    >
                      <SelectTrigger id="chat-model-provider">
                        <SelectValue placeholder={t("chooseProvider")} />
                      </SelectTrigger>
                      <SelectContent className="max-h-80">
                        {providers.map((entry) => {
                          const keyed = secrets.some((secret) => secret.purpose === entry.id);
                          return (
                            <SelectItem
                              key={entry.id}
                              value={entry.id}
                              // Type-to-search keys off this rather than off the mark's own
                              // title, which is otherwise part of the item's text.
                              textValue={entry.label}
                              // Outside the row: the trigger mirrors an item's text, and a
                              // tick there reads as "selected" rather than "has a key".
                              trailing={
                                keyed && (
                                  <Check className="text-muted-foreground ml-auto h-3.5 w-3.5 shrink-0" />
                                )
                              }
                            >
                              <ProviderRow provider={entry.id} name={entry.label} />
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>

                  {provider !== undefined && keys.length > 0 && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`${panelId}-connection`}>
                        {tRoot("personalModels.connection")}
                      </Label>
                      <Select value={chosenSecretId ?? ""} onValueChange={chooseConnection}>
                        <SelectTrigger id={`${panelId}-connection`}>
                          <SelectValue placeholder={tRoot("personalModels.chooseConnection")} />
                        </SelectTrigger>
                        <SelectContent>
                          {keys.map((secret) => (
                            <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                              {secret.name}
                              {secret.usage_scope === "personal" && (
                                <span className="text-muted-foreground ml-2 text-xs">
                                  {tRoot("personalModels.personal")}
                                </span>
                              )}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {personal && (
                        <p className="text-muted-foreground text-xs">
                          {tRoot("personalModels.personalUse")}
                        </p>
                      )}
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label htmlFor="chat-model-id">{t("model")}</Label>
                    {/* The Builder's own picker: the provider's catalog, searchable, and
                still able to carry an id that is not in it. */}
                    <ModelCombobox
                      id="chat-model-id"
                      value={model}
                      onChange={(next) => {
                        setModel(next);
                        setFailure(null);
                      }}
                      options={suggestions}
                      source={source}
                      loading={loadingModels}
                      disabled={provider === undefined}
                      placeholder={placeholderWords(modelPlaceholder(provider?.id), tRoot)}
                    />
                    {failure !== null && <p className="text-destructive text-xs">{failure}</p>}
                  </div>

                  {/* A key can be added here rather than on another page. A picker that can
              only offer what is already stored, and answers "add one in the Vault"
              when nothing is, is a dead end - and the provider is already chosen, so
              the purpose this key needs is known. */}
                  {provider !== undefined &&
                    !secrets.some((secret) => secret.purpose === provider.id) &&
                    (provider.kind === "openai_codex" ? (
                      <InlineChatGPTSignIn
                        suggestedName={provider.label}
                        onCreated={chooseConnection}
                      />
                    ) : (
                      <InlineSecret
                        kind="api_key"
                        purpose={provider.id}
                        suggestedName={provider.label}
                        onCreated={chooseConnection}
                      />
                    ))}

                  {provider !== undefined && ["anthropic", "openai"].includes(provider.id) && (
                    <PersonalApiConnection
                      provider={provider}
                      onCreated={(secret) => {
                        setCreatedConnection(secret);
                        chooseConnection(secret.id);
                      }}
                    />
                  )}

                  <Button type="button" className="w-full" disabled={!canApply} onClick={apply}>
                    {t("runModel")}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
