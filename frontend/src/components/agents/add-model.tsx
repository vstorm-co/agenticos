"use client";

import { useState } from "react";
import { Check, KeyRound, Plus, Save } from "lucide-react";

import { NO_FAILURE, submitFailure } from "@/lib/api-error";
import { hasKey, runsAgents } from "@/lib/model-profiles";
import { ModelCombobox } from "@/components/agents/model-combobox";
import { InlineChatGPTSignIn } from "@/components/vault/chatgpt-sign-in";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Button,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  useModelProviders,
  usePermissions,
  useProviderModels,
  useSecretPurposes,
  useSecrets,
} from "@/hooks";
import { Perm } from "@/types/permissions";
import type { ModelApi, ModelProfile, ProviderInfo } from "@/types/providers";
import { useTranslations } from "next-intl";

interface AddModelProps {
  /** Called with the new model once it exists, so the picker can select it. */
  onCreated: (profile: ModelProfile) => void;
  /**
   * Balance each started creation - or edit of `selected` - including one whose
   * form unmounts while awaiting it.
   */
  onCreationPendingChange?: (pending: boolean) => void;
  /**
   * The model the agent runs on today, which this form *starts on*.
   *
   * So the two selects say what is in use rather than "Choose a provider" above a
   * separate line repeating it. There used to be such a line, and with the labels
   * derived the way they are it read the model twice - but the deeper problem was
   * that the panel showed the answer in one place and asked the question in
   * another, when they are the same two fields.
   *
   * Its own state either way: this is still the form that *changes* the model, so
   * editing it must not write anything until somebody submits. The caller remounts
   * on a change of selection - see the `key` in `ModelProfilePicker`.
   */
  selected?: ModelProfile;
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
 * The provider to start on, when the organization has told us which one it uses.
 *
 * A deployment can reach every provider in the catalog, but the keys it holds
 * say which of them it can actually run on. An organization with exactly one key
 * was being asked to choose from a list with one real answer in it - and then to
 * choose the key underneath, which it also had one of.
 *
 * Exactly one, not "the first": two keys is a real choice and guessing between
 * them would put a model on the wrong account, which is a bill somebody else
 * pays. A secret's purpose *is* the provider id, which is what makes this a
 * lookup rather than a convention.
 */
export function soleKeyedProvider(
  providers: readonly { id: string }[],
  secrets: readonly { purpose?: string | null }[],
): string | undefined {
  const keyed = providers.filter((entry) => secrets.some((secret) => secret.purpose === entry.id));
  return keyed.length === 1 ? keyed[0]?.id : undefined;
}

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
  if (providerId === undefined) return { key: "agents.pickProviderFirst" };
  if (providerId === "openrouter") return "openai/gpt-5";
  return "gpt-5, claude-opus-5, gemini-3-pro…"; // i18n-exempt: example model ids
}

/** Catalog key for the hint under the field. */
export function modelHint(providerId: string | undefined): string {
  if (providerId === "openrouter") {
    return "agents.modelIdOpenRouterHint";
  }
  return "agents.modelIdProviderHint";
}

/**
 * A placeholder is either a key to translate or a literal example.
 *
 * **The keys above are absolute, and `t` has to be a root translator.** Two
 * components share these helpers and they read different namespaces - the Builder's
 * form is `agents`, the chat's picker is `chat.modelPicker` - so a namespace-relative
 * key resolved correctly for one caller and threw `MISSING_MESSAGE` for the other,
 * which Next.js renders as a console error over the picker. A helper whose
 * correctness depends on who called it is the defect; naming the namespace is the
 * fix, and it keeps the copy in one place rather than duplicated into both.
 */
export function placeholderWords(
  placeholder: { key: string } | string,
  t: (key: string) => string,
): string {
  return typeof placeholder === "string" ? placeholder : t(placeholder.key);
}

/** The key select's value for "no key": Radix refuses an empty string as an item's value. */
const NO_KEY = "none";

/** The same rule the backend applies, so the button says no before the server does. */
export function modelIdIsWellFormed(providerId: string, model: string): boolean {
  return providerId !== "openrouter" || model.includes("/");
}

/**
 * The API a profile gets when nobody picks one - the rule the service applies.
 *
 * The provider's own endpoint gets its `native_api`; an endpoint of the
 * reader's gets Chat Completions, which every OpenAI-compatible server
 * implements. Shown in the select rather than left implicit, because neither is
 * right everywhere: a regional OpenAI endpoint is an endpoint that serves
 * Responses.
 */
export function defaultApi(
  capabilities: Pick<ProviderInfo, "native_api"> | null,
  baseUrl: string,
): ModelApi | null {
  if (capabilities?.native_api == null) return null;
  return baseUrl.trim() === "" ? capabilities.native_api : "chat";
}

/**
 * What this form can mark, for `submitFailure`.
 *
 * Every refusal `POST /model-profiles` gives names one of these three now: a
 * bare OpenRouter id is about `model`, a keyless provider with nothing to reach
 * is about `base_url`, a keyed one with no key is about `secret_id` (#898), and
 * the endpoint checks were already there (#891). `base_url` is only offered
 * while that input is on screen - a refusal about a field the reader cannot see
 * belongs in the line above the button, which is at least readable. The API
 * select needs no entry: its one refusal is for a provider it is not drawn for.
 */
function markable(acceptsEndpoint: boolean): { fields: readonly string[] } {
  return { fields: acceptsEndpoint ? ["model", "base_url", "secret_id"] : ["model", "secret_id"] };
}

/** Keep endpoint variants readable and respect the profile label's 128-character limit. */
export function endpointProfileLabel(
  base: string,
  endpoint: string,
  existing: readonly string[],
  defaultEndpoint: string,
): string {
  const location = (
    endpoint
      .trim()
      .replace(/^https?:\/\//, "")
      .replace(/\/+$/, "") || defaultEndpoint
  ).slice(0, 64);
  const desired = `${base.slice(0, 125 - location.length)} · ${location}`;
  let result = desired;
  let index = 2;
  while (existing.includes(result)) {
    const suffix = ` (${index++})`;
    result = `${desired.slice(0, 128 - suffix.length)}${suffix}`;
  }
  return result;
}

export function AddModel({
  onCreated,
  onCreationPendingChange,
  onCancel,
  disabled,
  selected,
}: AddModelProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  // Root, for the absolute keys `modelPlaceholder` answers with - see the note on
  // `placeholderWords`. The chat's picker resolves the same keys from its own
  // namespace, so they cannot be relative to either caller's.
  const tRoot = useTranslations();
  const { createProfile, updateProfile, catalog, profiles = [] } = useModelProviders();
  const { purposes } = useSecretPurposes();
  const { secrets } = useSecrets();
  const { can } = usePermissions();
  // Storing a key is `secrets:edit`, which is a different permission from the
  // `connections:manage` that lets this form exist at all: somebody may define a
  // model profile for the organization and still not be allowed to write the
  // credential it runs on. Offering the form to them is a 403 dressed as a
  // control.
  const canStoreKey = can(Perm.secretsEdit);

  // What somebody picked, which is not the same as what the field shows: a
  // `null` here means nobody has picked yet, and the answer below is what the
  // organization already told us.
  const [pickedProvider, setPickedProvider] = useState<string | null>(selected?.provider ?? null);
  const [model, setModel] = useState(selected?.model ?? "");
  const [label, setLabel] = useState("");
  const [secretId, setSecretId] = useState(selected?.secret_id ?? "");
  const [baseUrl, setBaseUrl] = useState(selected?.base_url ?? "");
  // `null` until somebody picks, so the select follows the endpoint the way the
  // service's default does - typing a vLLM address moves it to Chat Completions.
  const [pickedApi, setPickedApi] = useState<ModelApi | null>(null);
  const [failure, setFailure] = useState(NO_FAILURE);
  const [naming, setNaming] = useState(false);

  const providers = purposes.filter((entry) => entry.category === "model_provider");
  /*
   * The provider an organization with exactly one key is obviously going to
   * pick, chosen for them.
   *
   * A deployment can reach every provider in the catalog, but the keys it holds
   * say which of them it can actually run on - and an organization with one key
   * was being asked to choose from a list with one real answer in it, then to
   * choose the key under it, which it also had one of.
   *
   * Derived rather than written into state by an effect: the keys arrive after
   * the first render, so an effect would be a second render that fills a field
   * somebody may already be typing in. The moment anybody picks anything,
   * `pickedProvider` wins and this stops being consulted.
   */
  const providerId = pickedProvider ?? soleKeyedProvider(providers, secrets) ?? "";
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
  // Only `openai` and `azure` serve both of OpenAI's APIs; for every other
  // provider there is nothing to choose and the field is not drawn.
  const choosesApi = (capabilities?.apis.length ?? 0) > 1;
  // Before anybody picks: the model in use's own choice while its provider and
  // endpoint are the ones on screen, and otherwise the default for what is - so
  // pointing the model in use at a vLLM does not carry Responses there with it.
  const startingApi =
    selected?.api != null &&
    providerId === selected.provider &&
    baseUrl.trim() === (selected.base_url ?? "")
      ? selected.api
      : defaultApi(capabilities, baseUrl);
  const api = choosesApi ? (pickedApi ?? startingApi) : null;
  // The keys already stored for this provider. A secret's purpose *is* the
  // provider id, which is what makes this a lookup rather than a convention.
  const keys = secrets.filter((secret) => secret.purpose === providerId);
  // A self-hosted model in use that runs with no key on purpose. The form offers
  // "no key" for it and starts there, instead of on the provider's first key: that
  // key is a suggestion for a new model, and saved onto this one it would be sent
  // to the endpoint for every agent on it (#2478).
  const offersNoKey =
    selected !== undefined &&
    selected.secret_id === null &&
    hasKey(selected) &&
    providerId === selected.provider;
  const chosenKey = secretId || (offersNoKey ? "" : (keys[0]?.id ?? ""));
  // What the provider publishes, where it publishes anything. Cached hard: a
  // catalog changes when a provider ships a model, not while a form is open.
  const {
    models: suggestions,
    refused,
    source,
    isLoading: loadingModels,
  } = useProviderModels(
    providerId,
    providerId === "openrouter" ? baseUrl.trim().replace(/\/+$/, "") || undefined : undefined,
  );
  const derivedLabel =
    provider && model.trim() ? `${provider.label} · ${model.trim()}` : t("howAgentsReferModel");

  // Whether the form is still showing the model it *started* on, untouched.
  //
  // What makes pre-filling safe: untouched, the form is showing the model in
  // use, so the form says so in place of a button - it used to offer "Use
  // this model", which selected the model already selected. Narrowed to `selected` rather
  // than "any profile with this pair", which was the first attempt and was wrong
  // twice over. It renamed the button whenever the organization happened to
  // already have the pair - so a flow that deliberately re-adds one found no
  // "Add model" to press - and worse, it would then have *selected the old
  // profile* while ignoring the endpoint, the key and the name somebody had
  // just typed. A form with any of those filled in is creating something,
  // whatever its first two fields say.
  const unchanged =
    selected !== undefined &&
    provider?.id === selected.provider &&
    model.trim() === selected.model &&
    label.trim() === "" &&
    baseUrl.trim() === (selected.base_url ?? "") &&
    api === (selected.api ?? null) &&
    // The key is part of "changed" too: an organization with two keys for one
    // provider can re-point a model at the other, and a submit that ignored this
    // would select the old profile and silently drop the key just picked. A model
    // whose key was deleted is changed by the key this form offers it, too -
    // "In use" above a model nothing can run on would be the wrong answer.
    (secretId === ""
      ? hasKey(selected) || chosenKey === ""
      : secretId === (selected.secret_id ?? ""));

  // The model in use with only its key, endpoint or API changed: that is an
  // edit of the model, not a second one (#2478). Every agent names a model by
  // its id, so saving it in place moves all of them at once - and adding a
  // second profile under the same derived name was refused as a duplicate. A
  // name typed in, or another provider or model, is a new model as before.
  const editing =
    selected !== undefined &&
    !unchanged &&
    provider?.id === selected.provider &&
    model.trim() === selected.model &&
    label.trim() === "";

  const endpointChanged =
    selected !== undefined &&
    provider?.id === selected.provider &&
    model.trim() === selected.model &&
    baseUrl.trim().replace(/\/+$/, "") !== (selected.base_url ?? "").replace(/\/+$/, "");
  const customEndpoint = acceptsEndpoint && baseUrl.trim() !== "";
  // Whether this model cannot run without an endpoint: a keyless provider with
  // no key to use. Only then is the field a question with an Ollama address for
  // an example. `keyless` alone is true of OpenAI too, because OpenAI-compatible
  // servers exist - so an OpenAI model with a key showed `localhost:11434` in its
  // empty Endpoint field, which read as an address filled in for it (#2478).
  const endpointRequired = (capabilities?.keyless ?? false) && chosenKey === "";
  const canSubmit =
    provider !== undefined &&
    model.trim() !== "" &&
    (chosenKey !== "" || keyOptional) &&
    modelIdIsWellFormed(provider.id, model.trim()) &&
    (!loadingModels || customEndpoint);

  // Both ways of choosing a key, because a refusal that outlives the value it
  // named accuses the one the reader has just picked.
  const chooseKey = (id: string) => {
    setSecretId(id);
    setFailure(NO_FAILURE);
  };

  const update = async () => {
    /* v8 ignore next -- `editing` is only true with a selection and a provider */
    if (selected === undefined || provider === undefined) return;
    setFailure(NO_FAILURE);
    onCreationPendingChange?.(true);
    try {
      await updateProfile.mutateAsync({
        id: selected.id,
        // All three, every time: the server compares them with what is stored
        // and writes only what differs, so what the form shows is what is saved.
        changes: {
          secret_id: chosenKey || null,
          base_url: customEndpoint ? baseUrl.trim() : null,
          api,
        },
      });
    } catch (error) {
      setFailure(submitFailure(error, markable(acceptsEndpoint), tErrors));
    } finally {
      onCreationPendingChange?.(false);
    }
  };

  const submit = async (separate = false) => {
    /* v8 ignore next -- the id comes from the list this select was built from */
    if (provider === undefined) return;
    setFailure(NO_FAILURE);
    // Every caller selects what this creates as a model to talk to - an agent's,
    // or the one describing a document's images - so a model the provider's
    // listing says is speech or embeddings is refused before a profile exists for
    // it (#2487). The listing is the provider's own API: an endpoint of the
    // reader's says nothing about it.
    const notChat = { fields: { model: t("notAChatModelRefused", { model: model.trim() }) } };
    if (!customEndpoint && refused.includes(model.trim())) {
      setFailure({ ...NO_FAILURE, ...notChat });
      return;
    }
    onCreationPendingChange?.(true);
    try {
      const baseLabel = `${provider.label} · ${model.trim()}`;
      const labels = [
        ...profiles.map((profile) => profile.label),
        ...(selected ? [selected.label] : []),
      ];
      const automaticLabel =
        separate || labels.includes(baseLabel)
          ? endpointProfileLabel(
              baseLabel,
              customEndpoint ? baseUrl : "",
              labels,
              t("defaultEndpoint"),
            )
          : baseLabel;
      const profile = await createProfile.mutateAsync({
        label: label.trim() || automaticLabel,
        provider: provider.id,
        model: model.trim(),
        // `null`, not `""`: the API distinguishes "no key, this is self-hosted"
        // from an unset field, and an empty string is neither.
        secret_id: chosenKey || null,
        // Only when the provider has one. Sending it otherwise is refused rather
        // than dropped, which is the right refusal but a pointless round trip.
        base_url: customEndpoint ? baseUrl.trim() : null,
        // Sent even when it is the default, so what the select shows is what is
        // stored - and a refusal, were there one, would be about this field.
        api,
      });
      // An id the listing did not classify still reaches here; the server
      // classifies the profile it created, and that answer is final.
      if (!runsAgents(profile)) {
        setFailure({ ...NO_FAILURE, ...notChat });
        return;
      }
      onCreated(profile);
    } catch (error) {
      // Caught, not left to reject: an unhandled rejection here is Next.js's
      // full-screen error overlay for what is a typo in one field. Which field
      // is the server's to say, and it names one for every refusal this endpoint
      // gives (#898) - so what is left for the line above the button is a
      // permission, a fault, or a conflict on the derived name.
      setFailure(submitFailure(error, markable(acceptsEndpoint), tErrors));
    } finally {
      onCreationPendingChange?.(false);
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
              setPickedProvider(value);
              setSecretId("");
              setModel("");
              setBaseUrl("");
              setPickedApi(null);
              setFailure(NO_FAILURE);
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
                    // The row draws a mark and a mark has a `<title>`, which
                    // counts as the item's text: without this, type-to-search
                    // matches the brand rather than the provider's name.
                    textValue={entry.label}
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

        {/*
          The provider's catalog, searchable, and still able to carry an id that
          is not in it. The list is never authoritative - providers ship models
          faster than any catalog here is refreshed - so "the one that came out
          this morning" stays expressible. What it is no longer is invisible:
          this was a text field with a `datalist`, which browsers surface only
          after a matching prefix is typed, so six hundred known models looked
          like none.
        */}
        <FormField htmlFor="add-model-id" label={t("model")} error={failure.fields.model}>
          <ModelCombobox
            id="add-model-id"
            value={model}
            onChange={(next) => {
              setModel(next);
              setFailure(NO_FAILURE);
            }}
            options={suggestions}
            source={source}
            loading={loadingModels}
            disabled={provider === undefined}
            placeholder={placeholderWords(modelPlaceholder(provider?.id), tRoot)}
          />
        </FormField>
      </div>

      {provider !== undefined && (
        <div className="space-y-1.5">
          {/* One key needs no question. The vault has exactly one OpenRouter
              key in most organizations, and a select with a single option is a
              decision somebody has to make about nothing. */}
          {keys.length === 1 && !offersNoKey && (
            <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <KeyRound className="h-3.5 w-3.5" />
              {t.rich("usingKey", {
                name: keys[0]!.name,
                strong: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
              })}
              <span className="font-mono">····{keys[0]?.hint}</span>
            </p>
          )}

          {(keys.length > 1 || (offersNoKey && keys.length > 0)) && (
            <>
              <Label htmlFor="add-model-key">{t("key")}</Label>
              <Select
                value={chosenKey || NO_KEY}
                onValueChange={(value) => chooseKey(value === NO_KEY ? "" : value)}
              >
                <SelectTrigger id="add-model-key">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {offersNoKey && <SelectItem value={NO_KEY}>{t("noKeyForEndpoint")}</SelectItem>}
                  {keys.map((secret) => (
                    <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
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
              {/* The sentence stays either way: a panel that simply drops the
                  form leaves somebody staring at a submit they cannot enable
                  with nothing saying why. What changes is what it points at -
                  a field here, or the person who may fill one in. */}
              <p className="text-muted-foreground text-xs">
                {canStoreKey
                  ? t("noProviderKeyAddOneHere", { provider: provider.label })
                  : t("noProviderKeyAskSomebody", { provider: provider.label })}
              </p>
              {canStoreKey && provider.kind === "openai_codex" && (
                <InlineChatGPTSignIn
                  suggestedName={provider.label}
                  onCreated={chooseKey}
                  disabled={disabled}
                />
              )}
              {canStoreKey && provider.kind !== "openai_codex" && (
                <InlineSecret
                  kind="api_key"
                  purpose={provider.id}
                  suggestedName={provider.label}
                  helpUrl={provider.help_url ?? undefined}
                  onCreated={chooseKey}
                  // Passed on rather than left to the submit button. This writes
                  // an organization-wide secret, and a caller that disabled the
                  // form - a dialog mid-save, a panel somebody may only read -
                  // did not mean "except the vault".
                  disabled={disabled}
                />
              )}
            </div>
          )}

          {/* No control to mark: the server refuses `secret_id` for being null,
              which is the state in which this block is a sentence rather than a
              select. */}
          {failure.fields.secret_id !== undefined && (
            <p className="text-destructive text-xs">{failure.fields.secret_id}</p>
          )}
        </div>
      )}

      {/* Only for providers whose SDK names an endpoint parameter. Offering it
          for the rest would collect a URL the client drops, and the API refuses
          it - which is the right refusal and a pointless one to walk into. */}
      {provider !== undefined && acceptsEndpoint && (
        <FormField
          htmlFor="add-model-endpoint"
          label={t("endpoint")}
          error={failure.fields.base_url}
          description={
            providerId === "openrouter"
              ? t("openRouterEndpointHint")
              : endpointRequired
                ? t("gatewayLitellmProxyModel")
                : t("optionalPointModelAt")
          }
        >
          <Input
            id="add-model-endpoint"
            value={baseUrl}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              setFailure(NO_FAILURE);
            }}
            placeholder={endpointRequired ? "http://localhost:11434/v1" : t("leaveEmptyProviderS")}
            autoComplete="off"
            spellCheck={false}
          />
        </FormField>
      )}

      {provider !== undefined && api !== null && (
        <FormField
          htmlFor="add-model-api"
          label={t("modelApi")}
          description={providerId === "azure" ? t("modelApiHintAzure") : t("modelApiHint")}
        >
          <Select
            value={api}
            onValueChange={(value) => {
              setPickedApi(capabilities?.apis.find((entry) => entry === value) ?? null);
              setFailure(NO_FAILURE);
            }}
          >
            <SelectTrigger id="add-model-api">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {capabilities?.apis.map((entry) => (
                <SelectItem key={entry} value={entry}>
                  {entry === "responses" ? t("modelApiResponses") : t("modelApiChat")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
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

      {/* Whatever this form has no input for - a permission, a fault, a
          conflict on a name it derived. It sat under the model id while that was
          the only place a refusal could land; now that all three name their own
          field, leaving it there would say the model was wrong when the answer
          was a 403. */}
      {failure.toast !== null && <p className="text-destructive text-xs">{failure.toast}</p>}

      {/* Said before the button rather than after the save: the change reaches
          every agent on this model, not only the one being built. */}
      {editing && selected !== undefined && !endpointChanged && (
        <p className="text-muted-foreground text-xs">
          {t("updateModelHint", { label: selected.label })}
        </p>
      )}

      {editing && endpointChanged && (
        <p className="text-muted-foreground text-xs">{t("separateEndpointHint")}</p>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {editing && endpointChanged && (
          <Button
            type="button"
            size="sm"
            disabled={disabled || !canSubmit || createProfile.isPending}
            onClick={() => void submit(true)}
          >
            <Plus className="h-4 w-4" />
            {t("addSeparateModel")}
          </Button>
        )}
        {unchanged && (
          // A state, not an action: there is nothing to add until a field changes.
          <span className="text-muted-foreground inline-flex h-8 items-center gap-1.5 text-sm">
            <Check className="text-success h-4 w-4" />
            {t("modelInUse")}
          </span>
        )}
        {editing && (
          <Button
            type="button"
            size="sm"
            variant={endpointChanged ? "outline" : "default"}
            disabled={disabled || !canSubmit || updateProfile.isPending}
            onClick={update}
          >
            <Save className="h-4 w-4" />
            {t("updateModel")}
          </Button>
        )}
        {!unchanged && !editing && (
          <Button
            type="button"
            size="sm"
            disabled={disabled || !canSubmit || createProfile.isPending}
            onClick={() => void submit()}
          >
            <Plus className="h-4 w-4" />
            {t("addModel")}
          </Button>
        )}
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            {t("cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
