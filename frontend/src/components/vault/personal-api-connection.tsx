"use client";

import { useId, useState } from "react";
import { KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, FormField, Input } from "@/components/ui";
import { usePermissions, useSecrets } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { Secret, SecretPurpose } from "@/types/secrets";

interface PersonalApiConnectionProps {
  provider: SecretPurpose;
  onCreated: (secret: Secret) => void;
  disabled?: boolean;
}

/** Store an explicitly personal API connection; saving does not make an inference request. */
export function PersonalApiConnection({
  provider,
  onCreated,
  disabled,
}: PersonalApiConnectionProps) {
  const t = useTranslations("personalModels");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { create } = useSecrets();
  const user = useAuthStore((state) => state.user);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!user || !can(Perm.secretsEdit) || !["anthropic", "openai"].includes(provider.id)) {
    return null;
  }
  if (provider.personal_supported !== true) {
    return <p className="text-muted-foreground text-xs">{t("personalUnavailable")}</p>;
  }

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => {
          setName(t("connectionName", { provider: provider.label, person: user.email }));
          setOpen(true);
        }}
      >
        <KeyRound className="size-3.5" aria-hidden />
        {t("connectApiKey", { provider: provider.label })}
      </Button>
    );
  }

  const submit = () => {
    setError(null);
    create.mutate(
      {
        name: name.trim(),
        purpose: provider.id,
        value: { kind: "api_key", api_key: key.trim() },
        visibility: "private",
        usage_scope: "personal",
      },
      {
        onSuccess: (secret) => {
          setKey("");
          if (
            secret.usage_scope !== "personal" ||
            secret.owner_user_id !== user.id ||
            secret.owner_user_id !== useAuthStore.getState().user?.id
          ) {
            setError(t("personalNotConfirmed"));
            return;
          }
          setOpen(false);
          onCreated(secret);
        },
        onError: (failure) => setError(getErrorMessage(failure, tErrors)),
      },
    );
  };
  const busy = disabled || create.isPending;

  return (
    <div className="border-border space-y-3 rounded-lg border border-dashed p-3">
      <p className="text-muted-foreground text-xs">{t("personalUse")}</p>
      <FormField label={t("name")} htmlFor={`${id}-name`}>
        <Input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} />
      </FormField>
      <FormField label={t("apiKey")} htmlFor={`${id}-key`}>
        <Input
          type="password"
          autoComplete="off"
          value={key}
          onChange={(event) => {
            setKey(event.target.value);
            setError(null);
          }}
          disabled={busy}
        />
      </FormField>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={busy || !name.trim() || !key.trim()}
          onClick={submit}
        >
          {t("saveConnection")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={create.isPending}
          onClick={() => {
            setKey("");
            setError(null);
            setOpen(false);
          }}
        >
          {t("cancel")}
        </Button>
        {provider.help_url && (
          <a
            href={provider.help_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground text-xs underline underline-offset-4"
          >
            {t("getApiKey")}
          </a>
        )}
      </div>
    </div>
  );
}
