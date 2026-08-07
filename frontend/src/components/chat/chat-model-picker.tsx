"use client";

import { useState } from "react";
import { Check } from "lucide-react";

import {
  modelIdIsWellFormed,
  modelPlaceholder,
  placeholderWords,
} from "@/components/agents/add-model";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import {
  useModelProviders,
  usePermissions,
  useProviderModels,
  useSecretPurposes,
  useSecrets,
} from "@/hooks";
import { getErrorMessage } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface ChatModelPickerProps {
  /** The model profile this conversation runs on, or null for the agent's own. */
  value: string | null;
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
 * **It checks `connections:manage` itself, over the whole form.** Creating that
 * profile is `POST /providers/model-profiles`, which is gated on
 * `Perm.CONNECTIONS_MANAGE` and on nothing else, while opening a conversation is
 * `agents:run` - so anybody who could type a message was offered these fields and
 * refused by the API after filling them in (#419). The gate is here rather than in
 * `ChatControls` because the permission belongs to the write and this component is
 * the only thing that makes it; the Model tab is also the one that opens by
 * default, so gating the tab button would leave the panel rendering anyway.
 *
 * It covers the fields and not only the submit, which is what #329 decided for the
 * Builder's copy of this control: three fields that lead nowhere are worse than
 * none. That does take the reuse path with it - matching an existing profile is a
 * read, and `GET /providers/model-profiles` is `agents:view` - but nothing here
 * lists those profiles, so reaching one means typing a provider and a model id
 * that happen to match, and every other combination is the 403 this exists to
 * stop. A sentence replaces the form, because a panel that goes blank explains
 * itself to nobody.
 */
export function ChatModelPicker({ value, onChange }: ChatModelPickerProps) {
  const t = useTranslations("chat.modelPicker");
  const { can } = usePermissions();
  const { profiles, createProfile } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();

  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  const { models: suggestions } = useProviderModels(providerId);
  const active = profiles.find((profile) => profile.id === value) ?? null;

  // Before the fields, not on the button: a disabled submit under three filled-in
  // fields still says "you could do this", and the answer here is that somebody
  // else has to. `can` answers false while the permission set is still loading,
  // so the form arrives once rather than appearing and being taken back.
  if (!can(Perm.connectionsManage)) {
    return <p className="text-muted-foreground text-xs">{t("needsConnectionsManage")}</p>;
  }

  const canApply =
    provider !== undefined &&
    model.trim() !== "" &&
    modelIdIsWellFormed(provider.id, model.trim()) &&
    !createProfile.isPending;

  const apply = async () => {
    if (provider === undefined) return;
    const modelId = model.trim();
    setFailure(null);

    // The organization may already have this exact model as a profile - reuse
    // it rather than minting a duplicate row per conversation.
    const existing = profiles.find(
      (profile) => profile.provider === provider.id && profile.model === modelId,
    );
    if (existing) {
      onChange(existing.id);
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
      onChange(profile.id);
    } catch (error) {
      // Caught, not left to reject: every refusal this endpoint gives is about
      // the model id, so it belongs under the field, where it can be fixed.
      setFailure(getErrorMessage(error));
    }
  };

  return (
    <div className="space-y-4">
      {active && (
        <p className="border-border bg-accent/40 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs">
          <ProviderIcon provider={active.provider} />
          <span className="min-w-0 flex-1 truncate">
            <span className="font-medium">{active.label}</span>
            <span className="text-muted-foreground block truncate font-mono">
              {active.provider} · {active.model}
            </span>
          </span>
          <Check className="text-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
        </p>
      )}

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
        {/* A list where the provider publishes one, and a plain field where it
            does not - the same control either way, because the list is never
            authoritative. */}
        <Input
          id="chat-model-id"
          list={suggestions.length > 0 ? "chat-model-suggestions" : undefined}
          value={model}
          onChange={(event) => {
            setModel(event.target.value);
            setFailure(null);
          }}
          disabled={provider === undefined}
          placeholder={placeholderWords(modelPlaceholder(provider?.id), t)}
          className="font-mono"
        />
        {suggestions.length > 0 && (
          <datalist id="chat-model-suggestions">
            {suggestions.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </datalist>
        )}
        {failure !== null && <p className="text-destructive text-xs">{failure}</p>}
      </div>

      {/* A key can be added here rather than on another page. A picker that can only
          offer what is already stored, and answers "add one in the Vault" when
          nothing is, is a dead end - and the provider is already chosen, so the
          purpose this key needs is known. */}
      {provider !== undefined && !secrets.some((secret) => secret.purpose === provider.id) && (
        <InlineSecret
          kind="api_key"
          purpose={provider.id}
          suggestedName={provider.label}
          onCreated={() => setFailure(null)}
        />
      )}

      <Button type="button" size="sm" disabled={!canApply} onClick={apply}>
        {t("runModel")}
      </Button>
    </div>
  );
}
