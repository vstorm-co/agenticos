"use client";

import { useState } from "react";
import { Check, KeyRound, Plus } from "lucide-react";

import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderIcon } from "@/components/vault/provider-icon";
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
import { useModelProviders, useProviderModels, useSecretPurposes, useSecrets } from "@/hooks";
import { getErrorMessage } from "@/lib/utils";
import type { ModelProfile } from "@/types/providers";

interface AddModelProps {
  /** Called with the new model once it exists, so the picker can select it. */
  onCreated: (profile: ModelProfile) => void;
  onCancel: () => void;
}

/**
 * Add a model: pick a provider, name the model, point it at a key.
 *
 * Every provider this deployment can reach is offered, not only the ones with a
 * key already — being told "no key yet" and handed a field is the answer to
 * "can we use OpenRouter?", and sending somebody to another page to find out is
 * the flow this replaces.
 *
 * The key comes from the vault, which is the store people actually manage: a
 * secret whose purpose is `openrouter` is what makes OpenRouter's models
 * runnable. One fact with one home, rather than a provider list here and a
 * separate credentials list somewhere else that had to agree with it.
 *
 * The model id is free text on purpose. Providers ship new ones weekly, and a
 * hard-coded list is wrong within a month — worse, wrong in the direction of
 * hiding the model somebody came here for.
 */
/**
 * What a model id looks like for this provider, before it is refused.
 *
 * Only OpenRouter needs saying, and it needs saying badly: it routes to other
 * people's models, so its ids carry the origin — `openai/gpt-5`, not `gpt-5` —
 * and the backend refuses a bare one. That refusal used to arrive after the
 * form was filled in, which is the wrong end of the interaction for something
 * this mechanical.
 */
export function modelPlaceholder(providerId: string | undefined): string {
  if (providerId === undefined) return "Pick a provider first";
  if (providerId === "openrouter") return "openai/gpt-5";
  return "gpt-5, claude-opus-5, gemini-3-pro…";
}

export function modelHint(providerId: string | undefined): string {
  if (providerId === "openrouter") {
    return "Namespaced by origin, as OpenRouter lists it — openai/gpt-5, anthropic/claude-opus-5.";
  }
  return "As the provider names it. Free text, because they ship new ones faster than any list here could be updated.";
}

/** The same rule the backend applies, so the button says no before the server does. */
export function modelIdIsWellFormed(providerId: string, model: string): boolean {
  return providerId !== "openrouter" || model.includes("/");
}

export function AddModel({ onCreated, onCancel }: AddModelProps) {
  const { createProfile } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();

  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [label, setLabel] = useState("");
  const [secretId, setSecretId] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [naming, setNaming] = useState(false);

  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  // The keys already stored for this provider. A secret's purpose *is* the
  // provider id, which is what makes this a lookup rather than a convention.
  const keys = secrets.filter((secret) => secret.purpose === providerId);
  const chosenKey = secretId || keys[0]?.id || "";
  // What the provider publishes, where it publishes anything. Cached hard: a
  // catalog changes when a provider ships a model, not while a form is open.
  const { models: suggestions } = useProviderModels(providerId);
  const derivedLabel =
    provider && model.trim()
      ? `${provider.label} · ${model.trim()}`
      : "How agents refer to this model";

  const canSubmit =
    provider !== undefined &&
    model.trim() !== "" &&
    chosenKey !== "" &&
    modelIdIsWellFormed(provider.id, model.trim());

  const submit = async () => {
    if (provider === undefined) return;
    setFailure(null);
    try {
      const profile = await createProfile.mutateAsync({
        label: label.trim() || `${provider.label} · ${model.trim()}`,
        provider: provider.id,
        model: model.trim(),
        secret_id: chosenKey,
      });
      onCreated(profile);
    } catch (error) {
      // Caught, not left to reject: an unhandled rejection here is Next.js's
      // full-screen error overlay for what is a typo in one field. Every
      // refusal this endpoint gives is about the model id — a bare id where the
      // provider namespaces them, an endpoint that is not a URL — so it belongs
      // under the field, where it can be fixed.
      setFailure(getErrorMessage(error));
    }
  };

  return (
    <div className="border-border bg-muted/20 space-y-4 rounded-xl border p-4">
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-1.5">
          <Label htmlFor="add-model-provider">Provider</Label>
          <Select
            value={providerId}
            onValueChange={(value) => {
              setProviderId(value);
              setSecretId("");
              setModel("");
              setFailure(null);
            }}
          >
            <SelectTrigger id="add-model-provider">
              <SelectValue placeholder="Choose a provider" />
            </SelectTrigger>
            <SelectContent className="max-h-80">
              {providers.map((entry) => {
                const keyed = secrets.some((secret) => secret.purpose === entry.id);
                return (
                  <SelectItem key={entry.id} value={entry.id}>
                    <span className="flex w-full items-center gap-2">
                      <ProviderIcon provider={entry.id} />
                      <span>{entry.label}</span>
                      {keyed && <Check className="text-muted-foreground ml-auto h-3.5 w-3.5" />}
                    </span>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="add-model-id">Model</Label>
          {/*
            A list where the provider publishes one, and a plain field where it
            does not — but the same control either way, because the list is
            never authoritative. Providers ship models faster than any catalog
            here is refreshed, and a select that cannot express "the one that
            came out this morning" is a select somebody has to work around.
          */}
          <Input
            id="add-model-id"
            list={suggestions.length > 0 ? "add-model-suggestions" : undefined}
            value={model}
            onChange={(event) => {
              setModel(event.target.value);
              setFailure(null);
            }}
            disabled={provider === undefined}
            placeholder={modelPlaceholder(provider?.id)}
            className="font-mono"
          />
          {suggestions.length > 0 && (
            <datalist id="add-model-suggestions">
              {suggestions.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </datalist>
          )}
          {failure !== null && <p className="text-destructive text-xs">{failure}</p>}
        </div>
      </div>

      {provider !== undefined && (
        <div className="space-y-1.5">
          {/* One key needs no question. The vault has exactly one OpenRouter
              key in most organizations, and a select with a single option is a
              decision somebody has to make about nothing. */}
          {keys.length === 1 && (
            <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <KeyRound className="h-3.5 w-3.5" />
              Using <span className="text-foreground font-medium">{keys[0]?.name}</span>
              <span className="font-mono">····{keys[0]?.hint}</span>
            </p>
          )}

          {keys.length > 1 && (
            <>
              <Label htmlFor="add-model-key">Key</Label>
              <Select value={chosenKey} onValueChange={setSecretId}>
                <SelectTrigger id="add-model-key">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {keys.map((secret) => (
                    <SelectItem key={secret.id} value={secret.id}>
                      {secret.name}
                      <span className="text-muted-foreground font-mono"> ····{secret.hint}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          )}

          {keys.length === 0 && (
            <div className="space-y-2">
              <p className="text-muted-foreground text-xs">
                No {provider.label} key in the vault yet. Add one here and it is stored for every
                agent in this organization.
              </p>
              <InlineSecret
                kind="api_key"
                purpose={provider.id}
                suggestedName={provider.label}
                helpUrl={provider.help_url ?? undefined}
                onCreated={setSecretId}
              />
            </div>
          )}
        </div>
      )}

      {/* The name is derived and almost never worth changing — it exists so an
          organization can run the same model twice under two keys and tell them
          apart. Behind a disclosure rather than in the way. */}
      {naming ? (
        <div className="space-y-1.5">
          <Label htmlFor="add-model-label">Name</Label>
          <Input
            id="add-model-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={derivedLabel}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setNaming(true)}
          className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4"
        >
          Name it something else
        </button>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button
          type="button"
          size="sm"
          disabled={!canSubmit || createProfile.isPending}
          onClick={submit}
        >
          <Plus className="h-4 w-4" />
          Add model
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
