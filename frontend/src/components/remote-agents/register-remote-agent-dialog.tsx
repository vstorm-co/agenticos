"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { ProviderRow } from "@/components/vault/provider-row";
import { InlineSecret } from "@/components/vault/inline-secret";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { useSecrets } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { ExternalAgent, ExternalAgentCreate } from "@/types/external-agents";

/** The Select's value for "send no key" - an item may not be empty. */
const NO_KEY = "__none__";

/** What a key stored from here is for, so the vault can say so later. */
const PURPOSE = "a2a";

/**
 * Register another vendor's agent by the address of its A2A agent card.
 *
 * The server reads the card while this dialog waits, so what it refuses - an
 * address it may not call, a page that is not a card - comes back here, on the
 * address field, and the form keeps what was typed.
 */
export function RegisterRemoteAgentDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: ExternalAgentCreate) => Promise<ExternalAgent>;
}) {
  const t = useTranslations("remoteAgents");
  const tErrors = useTranslations("errors");
  const { secrets } = useSecrets();
  const [cardUrl, setCardUrl] = useState("");
  const [slug, setSlug] = useState("");
  const [secretId, setSecretId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [optionalOpen, setOptionalOpen] = useState(false);
  const clearError = (field: string) =>
    setErrors((current) => {
      const next = { ...current };
      delete next[field];
      return next;
    });
  const keys = secrets.filter((secret) => secret.kind === "api_key");

  const reset = () => {
    setCardUrl("");
    setSlug("");
    setSecretId(null);
    setErrors({});
    setOptionalOpen(false);
  };

  async function submit() {
    if (pending || cardUrl.trim().length < 8) return;
    setPending(true);
    try {
      const created = await onSubmit({
        card_url: cardUrl.trim(),
        ...(slug.trim() ? { slug: slug.trim() } : {}),
        ...(secretId ? { secret_id: secretId } : {}),
      });
      toast.success(t("registered", { name: created.name }));
      reset();
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["card_url", "slug", "secret_id"], identifiedBy: "slug" },
        tErrors,
      );
      if (failure.fields.slug || failure.fields.secret_id) setOptionalOpen(true);
      // A card that could not be read is a refusal about the address, which the
      // server states as a sentence rather than a field: it goes on that field.
      setErrors(
        failure.toast !== null && Object.keys(failure.fields).length === 0
          ? { card_url: failure.toast }
          : failure.fields,
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent dismissible={!pending} className={cn(DIALOG_CONFIRM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("registerTitle")}</DialogTitle>
          <DialogDescription>{t("registerDescription")}</DialogDescription>
        </DialogHeader>

        <div className={cn(DIALOG_BODY, "space-y-4")}>
          <fieldset disabled={pending} className="space-y-4">
            <FormField
              label={t("cardUrl")}
              htmlFor="remote-agent-card"
              error={errors.card_url}
              description={t("cardUrlHint")}
            >
              <Input
                id="remote-agent-card"
                type="url"
                inputMode="url"
                // i18n-exempt: an example address, the same in every language
                placeholder="https://agents.example.com"
                value={cardUrl}
                onChange={(event) => {
                  setCardUrl(event.target.value);
                  clearError("card_url");
                }}
                autoComplete="off"
                maxLength={1000}
              />
            </FormField>

            <NativeDisclosure
              open={optionalOpen}
              onToggle={(event) => setOptionalOpen(event.currentTarget.open)}
              className="border-border rounded-xl border px-3 py-2"
            >
              <summary className="text-muted-foreground text-sm">{t("optionalSettings")}</summary>
              <div className="space-y-4 pt-3 pb-1">
                <FormField
                  label={t("handle")}
                  htmlFor="remote-agent-slug"
                  error={errors.slug}
                  description={t("handleHint")}
                >
                  <Input
                    id="remote-agent-slug"
                    value={slug}
                    onChange={(event) => {
                      setSlug(event.target.value);
                      clearError("slug");
                    }}
                    autoComplete="off"
                    maxLength={64}
                  />
                </FormField>

                <FormField
                  label={t("key")}
                  htmlFor="remote-agent-key"
                  error={errors.secret_id}
                  description={t("keyHint")}
                >
                  <Select
                    value={secretId ?? NO_KEY}
                    onValueChange={(next) => {
                      setSecretId(next === NO_KEY ? null : next);
                      clearError("secret_id");
                    }}
                  >
                    <SelectTrigger id="remote-agent-key">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_KEY}>{t("noKey")}</SelectItem>
                      {keys.map((secret) => (
                        <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                          <ProviderRow
                            provider={secret.purpose ?? "custom"}
                            name={secret.name}
                            hint={secret.hint}
                          />
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
                <InlineSecret
                  kind="api_key"
                  purpose={PURPOSE}
                  suggestedName={t("suggestedKeyName")}
                  onCreated={setSecretId}
                  disabled={pending}
                />
              </div>
            </NativeDisclosure>
          </fieldset>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => {
              reset();
              onOpenChange(false);
            }}
          >
            {t("cancel")}
          </Button>
          <Button onClick={submit} disabled={cardUrl.trim().length < 8 || pending}>
            {pending ? t("reading") : t("register")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
