"use client";

import { useState } from "react";
import { Check, KeyRound, Plus } from "lucide-react";

import { ModelCombobox } from "@/components/agents/model-combobox";
import { InlineSecret } from "@/components/vault/inline-secret";
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
import { useModelProviders, useProviderModels, useSecretPurposes, useSecrets } from "@/hooks";
import { getErrorMessage } from "@/lib/utils";
import type { ModelProfile } from "@/types/providers";
import { useTranslations } from "next-intl";

interface AddModelProps {
  /** Called with the new model once it exists, so the picker can select it. */
  onCreated: (profile: ModelProfile) => void;
  /**
   * The way out, where there is one.
   *
   * Omitted when this form is the panel rather than a state of it - the Builder
   * shows it unconditionally now, and a Cancel button that dismisses nothing is
   * a button whose only effect is to make somebody wonder what they cancelled.
   */
  onCancel?: () => void;
  disabled?: boolean;
}

/**
 * Add a model: pick a provider, name the model, point it at a key.
 *
 * Every provider this deployment can reach is offered, not only the ones with a
 * key already - being told "no key yet" and handed a field is the answer to
 * "can we use OpenRouter?", and sending somebody to another page to find out is
 * the flow this replaces.
 *
 * The key comes from the vault, which is the store people actually manage: a
 * secret whose purpose is `openrouter` is what makes OpenRouter's models
 * runnable. One fact with one home, rather than a provider list here and a
 * separate credentials list somewhere else that had to agree with it.
 *
 * The model id is free text on purpose. Providers ship new ones weekly, and a
 * hard-coded list is wrong within a month - worse, wrong in the direction of
 * hiding the model somebody came here for.
 */
/**
 * What a model id looks like for this provider, before it is refused.
 *
 * Only OpenRouter needs saying, and it needs saying badly: it routes to other
 * people's models, so its ids carry the origin - `openai/gpt-5`, not `gpt-5` -
 * and the backend refuses a bare one. That refusal used to arrive after the
 * form was filled in, which is the wrong end of the interaction for something
 * this mechanical.
 */
/**
 * What to show in the empty model field.
 *
 * A catalog key when there is something to say, and the *example ids themselves*
 * otherwise: `openai/gpt-5` is not English, it is what the provider calls the model,
 * and asking the catalog for it produced a missing-message error per keystroke.
 */
export function modelPlaceholder(providerId: string | undefined): { key: string } | string {
  if (providerId === undefined) return { key: "pickProviderFirst" };
  if (providerId === "openrouter") return "openai/gpt-5";
  return "gpt-5, claude-opus-5, gemini-3-pro…"; // i18n-exempt: example model ids
}

/** Catalog key for the hint under the field. */
export function modelHint(providerId: string | undefined): string {
  if (providerId === "openrouter") {
    return "modelIdOpenRouterHint";
  }
  return "modelIdProviderHint";
}

/** A placeholder is either a key to translate or a literal example. */
export function placeholderWords(
  placeholder: { key: string } | string,
  t: (key: string) => string,
): string {
  return typeof placeholder === "string" ? placeholder : t(placeholder.key);
}

/** The same rule the backend applies, so the button says no before the server does. */
export function modelIdIsWellFormed(providerId: string, model: string): boolean {
  return providerId !== "openrouter" || model.includes("/");
}

export function AddModel({ onCreated, onCancel, disabled }: AddModelProps) {
  const t = useTranslations("agents");
  const { createProfile, catalog } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();

  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [label, setLabel] = useState("");
  const [secretId, setSecretId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [naming, setNaming] = useState(false);

  const providers = purposes.filter((entry) => entry.category === "model_provider");
  const provider = providers.find((entry) => entry.id === providerId);
  // The purposes list says which providers a *key* can be stored for; only the
  // provider catalog knows whether one accepts an endpoint and whether it can run
  // without a key at all. Both facts are the API's to state - a hardcoded list
  // here would disagree with the resolver the moment a provider is added.
  const capabilities = catalog.find((entry) => entry.id === providerId) ?? null;
  const acceptsEndpoint = capabilities?.supports_base_url ?? false;
  // `keyless` means "can run with no credential", and it is true of `openai` too,
  // because OpenAI-compatible servers exist. So it does not identify a self-hosted
  // provider on its own - the endpoint does. A key is optional exactly when the
  // provider is keyless *and* an endpoint says where to send the request, which is
  // the rule `ModelProfileService.create_profile` enforces; anything looser here
  // would offer a submit the API refuses.
  const keyOptional = (capabilities?.keyless ?? false) && baseUrl.trim() !== "";
  // The keys already stored for this provider. A secret's purpose *is* the
  // provider id, which is what makes this a lookup rather than a convention.
  const keys = secrets.filter((secret) => secret.purpose === providerId);
  const chosenKey = secretId || keys[0]?.id || "";
  // What the provider publishes, where it publishes anything. Cached hard: a
  // catalog changes when a provider ships a model, not while a form is open.
  const { models: suggestions, source, isLoading: loadingModels } = useProviderModels(providerId);
  const derivedLabel =
    provider && model.trim() ? `${provider.label} · ${model.trim()}` : t("howAgentsReferModel");

  const canSubmit =
    provider !== undefined &&
    model.trim() !== "" &&
    (chosenKey !== "" || keyOptional) &&
    modelIdIsWellFormed(provider.id, model.trim());

  const submit = async () => {
    /* v8 ignore next -- the id comes from the list this select was built from */
    if (provider === undefined) return;
    setFailure(null);
    try {
      const profile = await createProfile.mutateAsync({
        label: label.trim() || `${provider.label} · ${model.trim()}`,
        provider: provider.id,
        model: model.trim(),
        // `null`, not `""`: the API distinguishes "no key, this is self-hosted"
        // from an unset field, and an empty string is neither.
        secret_id: chosenKey || null,
        // Only when the provider has one. Sending it otherwise is refused rather
        // than dropped, which is the right refusal but a pointless round trip.
        base_url: acceptsEndpoint && baseUrl.trim() !== "" ? baseUrl.trim() : null,
      });
      onCreated(profile);
    } catch (error) {
      // Caught, not left to reject: an unhandled rejection here is Next.js's
      // full-screen error overlay for what is a typo in one field. Every
      // refusal this endpoint gives is about the model id - a bare id where the
      // provider namespaces them, an endpoint that is not a URL - so it belongs
      // under the field, where it can be fixed.
      setFailure(getErrorMessage(error));
    }
  };

  return (
    <div className="border-border bg-muted/20 space-y-4 rounded-xl border p-4">
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="space-y-1.5">
          <Label htmlFor="add-model-provider">{t("provider")}</Label>
          <Select
            value={providerId}
            onValueChange={(value) => {
              setProviderId(value);
              setSecretId("");
              setModel("");
              setBaseUrl("");
              setFailure(null);
            }}
          >
            <SelectTrigger id="add-model-provider">
              <SelectValue placeholder={t("chooseProvider")} />
            </SelectTrigger>
            <SelectContent className="max-h-80">
              {providers.map((entry) => {
                const keyed = secrets.some((secret) => secret.purpose === entry.id);
                return (
                  <SelectItem
                    key={entry.id}
                    value={entry.id}
                    // Outside the row on purpose: the trigger mirrors an item's
                    // text, and a tick there would read as "selected" rather
                    // than "this provider already has a key".
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
          <Label htmlFor="add-model-id">{t("model")}</Label>
          {/*
            The provider's catalog, searchable, and still able to carry an id
            that is not in it. The list is never authoritative - providers ship
            models faster than any catalog here is refreshed - so "the one that
            came out this morning" stays expressible. What it is no longer is
            invisible: this was a text field with a `datalist`, which browsers
            surface only after a matching prefix is typed, so six hundred known
            models looked like none.
          */}
          <ModelCombobox
            id="add-model-id"
            value={model}
            onChange={(next) => {
              setModel(next);
              setFailure(null);
            }}
            options={suggestions}
            source={source}
            loading={loadingModels}
            disabled={provider === undefined}
            placeholder={placeholderWords(modelPlaceholder(provider?.id), t)}
          />
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
              <Label htmlFor="add-model-key">{t("key")}</Label>
              <Select value={chosenKey} onValueChange={setSecretId}>
                <SelectTrigger id="add-model-key">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {keys.map((secret) => (
                    <SelectItem key={secret.id} value={secret.id}>
                      {/* The provider is the filter this list was built with, so
                          it is also every row's mark - no `purpose` lookup. */}
                      <ProviderRow provider={provider.id} name={secret.name} hint={secret.hint} />
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

      {/* Only for providers whose SDK names an endpoint parameter. Offering it
          for the rest would collect a URL the client drops, and the API refuses
          it - which is the right refusal and a pointless one to walk into. */}
      {provider !== undefined && acceptsEndpoint && (
        <div className="space-y-1.5">
          <Label htmlFor="add-model-endpoint">{t("endpoint")}</Label>
          <Input
            id="add-model-endpoint"
            value={baseUrl}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              setFailure(null);
            }}
            placeholder={
              capabilities?.keyless === true
                ? "http://localhost:11434/v1"
                : t("leaveEmptyProviderS")
            }
            autoComplete="off"
            spellCheck={false}
          />
          <p className="text-muted-foreground text-xs">
            {capabilities?.keyless === true
              ? t("gatewayLitellmProxyModel")
              : t("optionalPointModelAt")}
          </p>
        </div>
      )}

      {/* The name is derived and almost never worth changing - it exists so an
          organization can run the same model twice under two keys and tell them
          apart. Behind a disclosure rather than in the way. */}
      {naming ? (
        <div className="space-y-1.5">
          <Label htmlFor="add-model-label">{t("name")}</Label>
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
          {t("nameSomethingElse")}
        </button>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button
          type="button"
          size="sm"
          disabled={disabled || !canSubmit || createProfile.isPending}
          onClick={submit}
        >
          <Plus className="h-4 w-4" />
          {t("addModel")}
        </Button>
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            {t("cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
