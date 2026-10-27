"use client";

import { useState } from "react";
import { Check } from "lucide-react";

import {
  modelIdIsWellFormed,
  modelPlaceholder,
  placeholderWords,
} from "@/components/agents/add-model";
import { ModelCombobox } from "@/components/agents/model-combobox";
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
import {
  useModelProviders,
  usePermissions,
  useProviderModels,
  useSecretPurposes,
  useSecrets,
} from "@/hooks";
import { hasKey, modelDetail, runsAgents, usableForAgents } from "@/lib/model-profiles";
import type { PublishedModel } from "@/types/agents";
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
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat.modelPicker");
  // Root, for the absolute keys `modelPlaceholder` answers with. Resolving them
  // through `t` above asked for `chat.modelPicker.pickProviderFirst`, which does
  // not exist - the copy lives under `agents`, where the Builder's form reads it.
  const tRoot = useTranslations();
  const { can } = usePermissions();
  const { profiles, createProfile } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();

  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  const {
    models: suggestions,
    refused,
    source,
    isLoading: loadingModels,
  } = useProviderModels(providerId);
  // An override profile and the agent's published model both carry
  // provider/model/label, so one summary renders whichever is current.
  const current = value === null ? agentModel : (profiles.find((p) => p.id === value) ?? null);
  const currentDetail = current ? modelDetail(current) : null;

  const matching = profiles.filter(
    (profile) => profile.provider === providerId && profile.model === model.trim(),
  );
  const hasCustomEndpoint = matching.some(
    (profile) => !!profile.base_url && usableForAgents(profile),
  );

  const canApply =
    provider !== undefined &&
    model.trim() !== "" &&
    modelIdIsWellFormed(provider.id, model.trim()) &&
    !createProfile.isPending &&
    (!loadingModels || hasCustomEndpoint);

  const apply = async () => {
    if (provider === undefined) return;
    const modelId = model.trim();
    setFailure(null);

    // The organization may already have this exact model as a profile - reuse
    // it rather than minting a duplicate row per conversation.
    // Several profiles can name the same vendor/model. Prefer one that can
    // chat, including a custom endpoint whose names the vendor cannot classify.
    const listingRefuses = refused.includes(modelId);
    const existing = matching.find(
      (profile) =>
        usableForAgents(profile) && (!!profile.base_url || (!loadingModels && !listingRefuses)),
    );
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

    const key = secrets.find((secret) => secret.purpose === provider.id);
    if (key === undefined) {
      // The form below offers to add one, so this says what is missing rather than
      // sending somebody to another page for it.
      setFailure(t("noProviderKey", { provider: provider.label }));
      return;
    }

    try {
      const profile = await createProfile.mutateAsync({
        label: `${provider.label} · ${modelId}`,
        provider: provider.id,
        model: modelId,
        secret_id: key.id,
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

  return (
    <div className="space-y-4">
      {current && (
        <p className="border-border bg-accent/40 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs">
          <ProviderIcon provider={current.provider} />
          <span className="min-w-0 flex-1 truncate">
            <span className="font-medium">{current.label}</span>
            {currentDetail !== null && (
              <span className="text-muted-foreground block truncate font-mono">
                {currentDetail}
              </span>
            )}
          </span>
          <span className="text-muted-foreground shrink-0 font-mono text-xs tracking-wider uppercase">
            {value === null ? t("agentModel") : t("thisChat")}
          </span>
        </p>
      )}

      {!can(Perm.connectionsManage) ? (
        <p className="text-muted-foreground text-xs">{t("needsConnectionsManage")}</p>
      ) : (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="chat-model-provider">{t("provider")}</Label>
            <Select
              value={providerId}
              onValueChange={(next) => {
                setProviderId(next);
                setModel("");
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
                onCreated={() => setFailure(null)}
              />
            ) : (
              <InlineSecret
                kind="api_key"
                purpose={provider.id}
                suggestedName={provider.label}
                onCreated={() => setFailure(null)}
              />
            ))}

          <Button type="button" size="sm" disabled={!canApply} onClick={apply}>
            {t("runModel")}
          </Button>
        </>
      )}
    </div>
  );
}
