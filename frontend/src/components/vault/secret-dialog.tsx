"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { toast } from "sonner";

import { ChatGPTSignInSteps } from "@/components/vault/chatgpt-sign-in";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { ProviderRow } from "@/components/vault/provider-row";
import { useChatGPTSignIn, useSecretPurposes } from "@/hooks";
import { cn } from "@/lib/utils";

import {
  SecretFields,
  isSecretComplete,
  secretFieldNames,
  toSecretPayload,
} from "@/components/vault/secret-form";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  MoreOptions,
  Textarea,
} from "@/components/ui";
import { kindInfo } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import type {
  NewSecret,
  Secret,
  SecretEdit,
  SecretKindInfo,
  SecretVisibility,
} from "@/types/secrets";
import type { StorableSecretKind } from "@/types/secrets";
import { useTranslations } from "next-intl";
import {
  DIALOG_BODY,
  DIALOG_COLUMN,
  DIALOG_CONFIRM,
  DIALOG_FORM,
  DIALOG_SCROLL_GUTTER,
} from "@/lib/dialog-sizes";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 1000;

interface AddSecretDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kinds: SecretKindInfo[];
  onSubmit: (data: NewSecret) => Promise<unknown>;
  isPending: boolean;
  /**
   * The service this dialog was opened *for* - a purpose id from the catalog.
   *
   * For a caller that is a shortcut rather than the vault page: the trigger
   * portal's "Add credentials" is asking for one specific thing, so opening on
   * Model provider with OpenAI chosen is asking the wrong question. The pickers
   * stay live - somebody who opened it by mistake can still use it - but they
   * start where the caller pointed them.
   */
  purposeId?: string;
}

/**
 * How the purposes are grouped in the picker, and in what order.
 *
 * Model providers first because that is what most people are here for, the
 * services next, and the escape hatch last - it is the answer when none of the
 * others fit, not a peer of them.
 */
const PURPOSE_GROUPS = [
  { id: "model_provider", words: "purposeModelProvider" },
  { id: "search", words: "purposeSearch" },
  { id: "observability", words: "purposeObservability" },
  // What a RAG sync connector reads documents with. Its own group because a
  // Drive service account is not a model provider's credential, and filing it
  // under Vertex AI - which takes the same *kind* - would group by the shape of
  // the secret rather than by what it is for (#937).
  { id: "connector", words: "purposeConnector" },
  { id: "other", words: "purposeOther" },
] as const;

type PurposeCategory = (typeof PURPOSE_GROUPS)[number]["id"];

/**
 * Store a secret a capability can be bound to.
 *
 * The service is asked first because it decides every field below it, and it is
 * asked at all because a capability declares which *kind* it needs - binding an
 * `api_key` where the code wants `aws_credentials` is refused at publish, and
 * that is a much later place to find out.
 */
export function AddSecretDialog({
  open,
  onOpenChange,
  kinds,
  onSubmit,
  isPending,
  purposeId,
}: AddSecretDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("vault");
  const { purposes } = useSecretPurposes();
  // `null` is "nobody has chosen yet", the same shape `name` below uses - and the
  // reason this is not seeded state plus an effect: the catalog is fetched, so on
  // the first render there is nothing to seed *from*, and a `setState` in an
  // effect is both a wasted render and something eslint refuses outright.
  // Deriving means the caller's service takes hold the moment the catalog lands.
  const [chosenCategory, setCategory] = useState<PurposeCategory | null>(null);
  const [chosenPurpose, setPurpose] = useState<string | null>(null);
  const opened = purposes.find((entry) => entry.id === purposeId) ?? null;
  const category = chosenCategory ?? (opened?.category as PurposeCategory) ?? "model_provider";
  const purpose = chosenPurpose ?? opened?.id ?? "";
  const [chosenVisibility, setVisibility] = useState<SecretVisibility | null>(null);
  // `null` is "nobody has typed a name", which is not the same as an empty one:
  // it is what lets the field follow the chosen service until somebody makes it
  // theirs. Once typed, it stays typed - including when typed back to blank.
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<StorableSecretKind>("api_key");
  const [value, setValue] = useState<Record<string, unknown>>({});
  const [callbackUrl, setCallbackUrl] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const chatgpt = useChatGPTSignIn();

  const inCategory = purposes.filter((entry) => entry.category === category);
  // Falls back to the first in the category so the select is never blank: an
  // empty trigger reads as a control that failed to load its options.
  const chosen = purposes.find((entry) => entry.id === purpose) ?? inCategory[0] ?? null;
  // The shape follows from the service for everything except `custom`: OpenAI
  // takes an API key, Bedrock takes an AWS pair, and asking somebody to pick
  // that a second time is asking them to get it wrong.
  const effectiveKind = chosen && chosen.id !== "custom" ? chosen.kind : kind;
  const isCustom = chosen === null || chosen.id === "custom";
  const info = kindInfo(kinds, effectiveKind);
  // The one shape nobody types: it is stored by signing in, and it is somebody's
  // own subscription - so it starts private, where every other key starts shared.
  const signsIn = effectiveKind === "openai_codex";
  const visibility = chosenVisibility ?? (signsIn ? "private" : "org");
  const pending = isPending || chatgpt.create.isPending;
  // What the field shows: what was typed, or the service's own name. Switching
  // from OpenAI to Anthropic with the field still reading "OpenAI" leaves a key
  // named after the wrong provider, in a list people scan by name.
  const suggestedName = chosen === null || chosen.id === "custom" ? "" : chosen.label;
  const shownName = name ?? suggestedName;
  const complete =
    shownName.trim().length > 0 &&
    info !== null &&
    (signsIn ? callbackUrl.trim() !== "" : isSecretComplete(info.json_schema, value));

  function reset() {
    setCategory(null);
    setPurpose(null);
    setVisibility(null);
    setName(null);
    setDescription("");
    setValue({});
    setCallbackUrl("");
    setErrors({});
  }

  /** A different family means a different list, and nothing chosen from it yet. */
  function chooseCategory(next: PurposeCategory) {
    setCategory(next);
    // A different family means a different list, and nothing chosen from it - but
    // `null` here would fall back to the caller's service, which is in the family
    // just left. The empty string is "chosen nothing", and the list's first entry
    // stands in for it below.
    setPurpose("");
    setValue({});
    setCallbackUrl("");
    setErrors({});
  }

  /** A different service asks for a different shape, and suggests its own name. */
  function choosePurpose(next: string) {
    setPurpose(next);
    setValue({});
    setCallbackUrl("");
    setErrors({});
  }

  /** Another shape asks other questions, so the answers to the old ones go. */
  function chooseKind(next: string) {
    setKind(next as StorableSecretKind);
    setValue({});
    setErrors({});
  }

  async function submit() {
    if (info === null) return;
    try {
      if (signsIn) {
        await chatgpt.create.mutateAsync({
          name: shownName.trim(),
          description: description.trim() || null,
          visibility,
          callback_url: callbackUrl.trim(),
        });
      } else {
        await onSubmit({
          name: shownName.trim(),
          description: description.trim() || null,
          value: toSecretPayload(effectiveKind, value),
          purpose: chosen?.id ?? "custom",
          visibility,
        });
      }
      onOpenChange(false);
      reset();
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: [
            "name",
            "description",
            ...(signsIn ? ["callback_url"] : secretFieldNames(info.json_schema)),
          ],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      {/* One column that scrolls as a whole, in the order somebody fills it:
          what it is for, which service, the key itself, what to call it and
          who may use it - the note folded away. The cards with a subtitle each,
          the paired selects and a scroll box inside the dialog read as a form
          about the form. */}
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("addSecret")}</DialogTitle>
          <DialogDescription>{t("encryptedBoundOrganizationAgent")}</DialogDescription>
        </DialogHeader>

        <div className={cn(DIALOG_BODY, "space-y-5")}>
          {/* A caption over a group of buttons, not a `Label`: a label names
              one control, and this one names five. */}
          <div className="space-y-2">
            <p id="secret-purpose-family" className="text-sm leading-none font-medium">
              {t("what")}
            </p>
            {/* A tile per kind of key, each wearing the marks of the services it
                covers - "Model provider" says less at a glance than the OpenAI,
                Anthropic and Gemini marks do. Taken from the catalog, so a new
                service shows up here without a change to this file. */}
            <div
              role="group"
              aria-labelledby="secret-purpose-family"
              className="grid grid-cols-2 gap-2 sm:grid-cols-3"
            >
              {PURPOSE_GROUPS.map((group) => (
                <button
                  key={group.id}
                  type="button"
                  onClick={() => chooseCategory(group.id)}
                  aria-pressed={category === group.id}
                  title={t(`${group.words}Hint`)}
                  className={cn(
                    "flex flex-col items-start gap-2 rounded-xl border p-3 text-left text-sm font-medium transition-colors",
                    category === group.id
                      ? "border-foreground bg-accent text-foreground"
                      : "border-input text-muted-foreground hover:text-foreground hover:bg-accent/60",
                  )}
                >
                  <span className="text-foreground flex h-5 items-center gap-1.5" aria-hidden>
                    {group.id === "other" ? (
                      <KeyRound className="h-4 w-4" />
                    ) : (
                      purposes
                        .filter((entry) => entry.category === group.id)
                        .slice(0, 3)
                        .map((entry) => (
                          <ProviderIcon
                            key={entry.id}
                            provider={entry.id}
                            brand={entry.icon}
                            className="h-4 w-4"
                          />
                        ))
                    )}
                  </span>
                  {t(group.words)}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="secret-purpose">
              {category === "other" ? t("service") : t("whichOne")}
            </Label>
            {/* The entry that is in force, fallback included - the raw choice
                  is empty until somebody picks, and a trigger bound to it read as
                  blank while the hint under it already named the first service. */}
            <Select value={chosen?.id ?? ""} onValueChange={choosePurpose}>
              <SelectTrigger id="secret-purpose">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-80">
                {inCategory.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id} textValue={entry.label}>
                    {/* The mark, where there is one. A vault is scanned rather
                          than read, and a logo is what the eye lands on. */}
                    <ProviderRow provider={entry.id} name={entry.label} brand={entry.icon} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {chosen?.description ?? t("namingServiceWhatLets")}
              {chosen?.help_url && (
                <>
                  {" "}
                  <a
                    href={chosen.help_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="underline underline-offset-4"
                  >
                    {t("whereDoIGet2")}
                  </a>
                </>
              )}
            </p>
          </div>

          {info && signsIn && (
            <ChatGPTSignInSteps
              callbackUrl={callbackUrl}
              onCallbackUrlChange={setCallbackUrl}
              error={errors.callback_url}
              disabled={pending}
              idPrefix="secret"
            />
          )}
          {info && !signsIn && (
            <SecretFields
              info={info}
              value={value}
              onChange={setValue}
              disabled={isPending}
              idPrefix="secret"
              errors={errors}
            />
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("name")}
              htmlFor="secret-name"
              error={errors.name}
              // Full width unless the Kind select is beside it: a lone half-width
              // input with empty space to its right reads as a field that failed
              // to render its neighbour.
              className={isCustom ? undefined : "sm:col-span-2"}
            >
              <Input
                value={shownName}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("zendeskApiToken")}
                maxLength={MAX_NAME}
              />
            </FormField>

            {/* Only for `custom`: every named service declares the shape it
                takes, and asking twice is asking somebody to disagree with the
                server. */}
            {isCustom && (
              <div className="space-y-2">
                <Label htmlFor="secret-kind">{t("kind")}</Label>
                <Select value={kind} onValueChange={chooseKind}>
                  <SelectTrigger id="secret-kind">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {/* Not a shape a custom secret can take: a ChatGPT
                        sign-in is stored by signing in, under its provider. */}
                    {kinds
                      .filter((entry) => entry.kind !== "openai_codex")
                      .map((entry) => (
                        <SelectItem key={entry.kind} value={entry.kind}>
                          {entry.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="secret-visibility">{t("whoCanUse")}</Label>
            <Select
              value={visibility}
              onValueChange={(next) => setVisibility(next as SecretVisibility)}
            >
              <SelectTrigger id="secret-visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="org">{t("everyoneOrganization")}</SelectItem>
                <SelectItem value="private">{t("onlyMe")}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {visibility === "org" ? t("sharedAccountAnyoneHere") : t("yoursAloneYouCan")}{" "}
              {t("eitherWayAgentRunsWithIt")}
            </p>
          </div>

          <MoreOptions label={t("moreOptions")}>
            <FormField
              label={t("noteOptional")}
              htmlFor="secret-description"
              error={errors.description}
              description={t("shownNextPickerWhich")}
            >
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={2}
                maxLength={MAX_DESCRIPTION}
              />
            </FormField>
          </MoreOptions>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button onClick={submit} disabled={!complete || pending}>
            {t("storeSecret")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface RotateSecretDialogProps {
  /** The secret being rotated; `null` closes the dialog. */
  secret: Secret | null;
  onOpenChange: (open: boolean) => void;
  kinds: SecretKindInfo[];
  onSubmit: (data: SecretEdit) => Promise<unknown>;
  isPending: boolean;
}

/**
 * Replace a secret's value while keeping its id.
 *
 * This is the operation the vault exists to make ordinary. Every agent binding
 * names a secret by id, so rotating one leaves all of them working - where
 * deleting it and storing a new one leaves each of them pointing at something
 * this organization no longer has, and says so only at the next run.
 *
 * The kind is fixed and shown rather than offered: the server refuses a change
 * of shape with a 400, because a capability bound to an `api_key` cannot be
 * handed an AWS key pair by whoever happened to rotate it.
 */
export function RotateSecretDialog({
  secret,
  onOpenChange,
  kinds,
  onSubmit,
  isPending,
}: RotateSecretDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("vault");
  const [value, setValue] = useState<Record<string, unknown>>({});
  const [callbackUrl, setCallbackUrl] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const chatgpt = useChatGPTSignIn();

  const info = secret === null ? null : kindInfo(kinds, secret.kind);
  // A ChatGPT sign-in is rotated by signing in again: there is no value to type,
  // and the grant a refused refresh left behind is the thing being replaced.
  const reconnects = secret?.kind === "openai_codex";
  const pending = isPending || chatgpt.reconnect.isPending;
  const complete =
    info !== null &&
    (reconnects ? callbackUrl.trim() !== "" : isSecretComplete(info.json_schema, value));

  function clear() {
    setValue({});
    setCallbackUrl("");
    setErrors({});
  }

  async function submit() {
    if (secret === null || info === null) return;
    try {
      if (reconnects) {
        await chatgpt.reconnect.mutateAsync({ id: secret.id, callback_url: callbackUrl.trim() });
      } else {
        await onSubmit({ id: secret.id, value: toSecretPayload(secret.kind, value) });
      }
      onOpenChange(false);
      clear();
    } catch (error) {
      const fields = reconnects ? ["callback_url"] : secretFieldNames(info.json_schema);
      const failure = submitFailure(error, { fields }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(next) => {
        if (!next) clear();
        onOpenChange(next);
      }}
    >
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>
            {t(reconnects ? "chatgptReconnectNamed" : "rotateNamed", { name: secret?.name ?? "" })}
          </DialogTitle>
          <DialogDescription>
            {reconnects ? t("chatgptReconnectBody") : t("newValueReplacesOld")}
          </DialogDescription>
        </DialogHeader>

        {secret && info && (
          <div className={cn("max-h-[60vh] space-y-4 overflow-y-auto pl-1", DIALOG_SCROLL_GUTTER)}>
            <p className="text-muted-foreground text-xs">
              {t("nameCurrentlyEnds", { name: info.name })}{" "}
              <span className="font-mono">····{secret.hint}</span>
            </p>
            {reconnects ? (
              <ChatGPTSignInSteps
                callbackUrl={callbackUrl}
                onCallbackUrlChange={setCallbackUrl}
                error={errors.callback_url}
                disabled={pending}
                idPrefix="rotate"
              />
            ) : (
              <SecretFields
                info={info}
                value={value}
                onChange={setValue}
                disabled={isPending}
                idPrefix="rotate"
                errors={errors}
              />
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel3")}
          </Button>
          <Button onClick={submit} disabled={!complete || pending}>
            {reconnects ? t("chatgptReconnect") : t("rotate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
