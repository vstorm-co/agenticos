"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ProviderRow } from "@/components/vault/provider-row";
import { useSecretPurposes } from "@/hooks";
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

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 1000;

interface AddSecretDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kinds: SecretKindInfo[];
  onSubmit: (data: NewSecret) => Promise<unknown>;
  isPending: boolean;
}

/**
 * Store a secret a capability can be bound to.
 *
 * The kind is asked first because it decides every field below it, and it is
 * asked at all because a capability declares which kind it needs - binding an
 * `api_key` where the code wants `aws_credentials` is refused at publish, and
 * that is a much later place to find out.
 */
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
  { id: "other", words: "purposeOther" },
] as const;

type PurposeCategory = (typeof PURPOSE_GROUPS)[number]["id"];

export function AddSecretDialog({
  open,
  onOpenChange,
  kinds,
  onSubmit,
  isPending,
}: AddSecretDialogProps) {
  const t = useTranslations("vault");
  const { purposes } = useSecretPurposes();
  const [category, setCategory] = useState<PurposeCategory>("model_provider");
  const [purpose, setPurpose] = useState("");
  const [visibility, setVisibility] = useState<SecretVisibility>("org");
  // `null` is "nobody has typed a name", which is not the same as an empty one:
  // it is what lets the field follow the chosen service until somebody makes it
  // theirs. Once typed, it stays typed - including when typed back to blank.
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<StorableSecretKind>("api_key");
  const [value, setValue] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

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
  // What the field shows: what was typed, or the service's own name. Switching
  // from OpenAI to Anthropic with the field still reading "OpenAI" leaves a key
  // named after the wrong provider, in a list people scan by name.
  const suggestedName = chosen === null || chosen.id === "custom" ? "" : chosen.label;
  const shownName = name ?? suggestedName;
  const complete =
    shownName.trim().length > 0 && info !== null && isSecretComplete(info.json_schema, value);

  function reset() {
    setCategory("model_provider");
    setPurpose("");
    setVisibility("org");
    setName(null);
    setDescription("");
    setValue({});
    setErrors({});
  }

  /** A different family means a different list, and nothing chosen from it yet. */
  function chooseCategory(next: PurposeCategory) {
    setCategory(next);
    setPurpose("");
    setValue({});
    setErrors({});
  }

  /** A different service asks for a different shape, and suggests its own name. */
  function choosePurpose(next: string) {
    setPurpose(next);
    setValue({});
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
      await onSubmit({
        name: shownName.trim(),
        description: description.trim() || null,
        value: toSecretPayload(effectiveKind, value),
        purpose: chosen?.id ?? "custom",
        visibility,
      });
      onOpenChange(false);
      reset();
    } catch (error) {
      const failure = submitFailure(error, {
        fields: ["name", "description", ...secretFieldNames(info.json_schema)],
        identifiedBy: "name",
      });
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
      {/* Wider than the default dialog. Six questions stacked in 512px is a
          form that scrolls before it is read; at this width the pairs that
          belong together sit on one line and the whole thing fits on a screen. */}
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("addSecret")}</DialogTitle>
          <DialogDescription>{t("encryptedBoundOrganizationAgent")}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[65vh] space-y-5 overflow-y-auto px-1">
          {/* First, because it decides everything below it: which shape the
              form asks for, what the key unlocks, and where it can be picked. */}
          {/* Two steps rather than one list of thirty-one. The first question
              has three answers and rules out most of the second - picking
              "Web search" turns a scroll through every model provider into a
              choice between three services. */}
          {/* A caption over a group of buttons, not a `Label`: a label names
              one control, and this one names three. `role="group"` with
              `aria-labelledby` is how a screen reader is told the same thing
              the heading tells everyone else. */}
          <div className="space-y-2">
            <p id="secret-purpose-family" className="text-sm leading-none font-medium">
              {t("what")}
            </p>
            <div
              role="group"
              aria-labelledby="secret-purpose-family"
              className="grid grid-cols-3 gap-2"
            >
              {PURPOSE_GROUPS.map((group) => (
                <button
                  key={group.id}
                  type="button"
                  onClick={() => chooseCategory(group.id)}
                  aria-pressed={category === group.id}
                  className={cn(
                    "rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                    category === group.id
                      ? "border-brand bg-brand/5 text-foreground"
                      : "border-input hover:bg-accent/50 text-muted-foreground",
                  )}
                >
                  <span className="block font-medium">{t(group.words)}</span>
                  <span className="text-muted-foreground block text-xs">
                    {t(`${group.words}Hint`)}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* The two questions that decide what this key is and who it is for,
              side by side: at this width they read as one decision, which is
              what they are. */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="secret-purpose">
                {category === "other" ? t("service") : t("whichOne")}
              </Label>
              <Select value={purpose} onValueChange={choosePurpose}>
                <SelectTrigger id="secret-purpose">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-h-80">
                  {inCategory.map((entry) => (
                    <SelectItem key={entry.id} value={entry.id} textValue={entry.label}>
                      {/* The mark, where there is one. A vault is scanned rather
                          than read, and a logo is what the eye lands on. */}
                      <ProviderRow provider={entry.id} name={entry.label} />
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
                {visibility === "org" ? t("sharedAccountAnyoneHere") : t("yoursAloneYouCan")} Either
                way, an agent that uses this key runs with it for everyone who can run that agent.
              </p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("name")}
              htmlFor="secret-name"
              error={errors.name}
              description={t("howYouWillRecognise")}
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
                    {kinds.map((entry) => (
                      <SelectItem key={entry.kind} value={entry.kind}>
                        {entry.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

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

          {info && (
            <SecretFields
              info={info}
              value={value}
              onChange={setValue}
              disabled={isPending}
              idPrefix="secret"
              errors={errors}
            />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button onClick={submit} disabled={!complete || isPending}>
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
  const t = useTranslations("vault");
  const [value, setValue] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const info = secret === null ? null : kindInfo(kinds, secret.kind);
  const complete = info !== null && isSecretComplete(info.json_schema, value);

  async function submit() {
    if (secret === null || info === null) return;
    try {
      await onSubmit({ id: secret.id, value: toSecretPayload(secret.kind, value) });
      onOpenChange(false);
      setValue({});
      setErrors({});
    } catch (error) {
      const failure = submitFailure(error, { fields: secretFieldNames(info.json_schema) });
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(next) => {
        if (!next) {
          setValue({});
          setErrors({});
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rotate {secret?.name}</DialogTitle>
          <DialogDescription>{t("newValueReplacesOld")}</DialogDescription>
        </DialogHeader>

        {secret && info && (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto px-1">
            <p className="text-muted-foreground text-xs">
              {info.name} · currently ends <span className="font-mono">····{secret.hint}</span>
            </p>
            <SecretFields
              info={info}
              value={value}
              onChange={setValue}
              disabled={isPending}
              idPrefix="rotate"
              errors={errors}
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel3")}
          </Button>
          <Button onClick={submit} disabled={!complete || isPending}>
            {t("rotate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
