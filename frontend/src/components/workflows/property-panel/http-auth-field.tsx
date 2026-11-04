"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SecretPicker } from "@/components/workflows/pickers/secret-picker";
import { isRecord } from "./schema-model";

const MODES = ["none", "bearer", "header", "query", "basic"] as const;
type AuthKind = (typeof MODES)[number];
export interface HttpAuthentication {
  kind: AuthKind;
  secret_id?: string | null;
  header_name?: string;
  header_prefix?: string;
  query_name?: string;
}

/** Only references leave this form; the vault alone receives credential values. */
export function HttpAuthField({
  value,
  url,
  disabled,
  errors,
  onChange,
}: {
  value: unknown;
  url: unknown;
  disabled?: boolean;
  errors?: ReadonlyMap<string, string>;
  onChange: (next: HttpAuthentication) => void;
}) {
  const t = useTranslations("workflows");
  const id = useId();
  const stored = isRecord(value) ? value : {};
  const kind = MODES.find((mode) => mode === stored.kind) ?? "none";
  const secretId = typeof stored.secret_id === "string" ? stored.secret_id : null;
  function configuration(next: AuthKind): HttpAuthentication {
    if (next === "none") return { kind: "none" };
    return {
      kind: next,
      secret_id: secretId,
      ...(next === "header"
        ? {
            header_name: typeof stored.header_name === "string" ? stored.header_name : "X-API-Key",
            ...(typeof stored.header_prefix === "string"
              ? { header_prefix: stored.header_prefix }
              : {}),
          }
        : {}),
      ...(next === "query"
        ? { query_name: typeof stored.query_name === "string" ? stored.query_name : "api_key" }
        : {}),
    };
  }
  // The server's resource check uses dots; local schema checks use binding paths.
  const path = (field: string) =>
    errors?.has(`auth.${field}`) ? `auth.${field}` : `auth/${field}`;
  const error = (field: string) => errors?.get(path(field));
  let origin: string | undefined;
  if (typeof url === "string") {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") origin = parsed.origin;
    } catch {
      /* A bound or unfinished URL has no origin to suggest. */
    }
  }
  const current = configuration(kind);
  return (
    <fieldset className="space-y-4 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{t("httpAuthTitle")}</legend>
      <div className="space-y-2" data-field={path("kind")}>
        <Label htmlFor={`${id}-kind`}>{t("httpAuthMethod")}</Label>
        <Select
          value={kind}
          disabled={disabled}
          onValueChange={(next) => {
            const mode = MODES.find((mode) => mode === next);
            if (mode) onChange(configuration(mode));
          }}
        >
          <SelectTrigger id={`${id}-kind`} aria-label={t("httpAuthMethod")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MODES.map((mode) => (
              <SelectItem key={mode} value={mode}>
                {t(`httpAuthModes.${mode}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {(errors?.get("auth") ?? error("kind")) && (
          <p className="text-destructive text-xs">{errors?.get("auth") ?? error("kind")}</p>
        )}
      </div>
      {kind !== "none" && (
        <>
          <div data-field={path("secret_id")}>
            <SecretPicker
              label={t("httpAuthCredential")}
              kind="http_credential"
              value={secretId}
              initialValue={origin ? { origins: [origin] } : undefined}
              onChange={(next) => onChange({ ...current, secret_id: next })}
              disabled={disabled}
              error={error("secret_id")}
            />
          </div>
          <p className="text-muted-foreground text-xs">{t("httpAuthVaultHint")}</p>
          {kind === "basic" && (
            <p className="text-muted-foreground text-xs">{t("httpAuthBasicHint")}</p>
          )}
          {kind === "header" && (
            <>
              <div className="space-y-2" data-field={path("header_name")}>
                <Label htmlFor={`${id}-header`}>{t("httpAuthHeader")}</Label>
                <Input
                  id={`${id}-header`}
                  value={current.header_name ?? ""}
                  disabled={disabled}
                  onChange={(event) => onChange({ ...current, header_name: event.target.value })}
                />
                {error("header_name") && (
                  <p className="text-destructive text-xs">{error("header_name")}</p>
                )}
              </div>
              <div className="space-y-2" data-field={path("header_prefix")}>
                <Label htmlFor={`${id}-prefix`}>{t("httpAuthPrefix")}</Label>
                <Input
                  id={`${id}-prefix`}
                  value={current.header_prefix ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({ ...current, header_prefix: event.target.value || undefined })
                  }
                />
                <p className="text-muted-foreground text-xs">{t("httpAuthPrefixHint")}</p>
                {error("header_prefix") && (
                  <p className="text-destructive text-xs">{error("header_prefix")}</p>
                )}
              </div>
            </>
          )}
          {kind === "query" && (
            <div className="space-y-2" data-field={path("query_name")}>
              <Label htmlFor={`${id}-query`}>{t("httpAuthQuery")}</Label>
              <Input
                id={`${id}-query`}
                value={current.query_name ?? ""}
                disabled={disabled}
                onChange={(event) => onChange({ ...current, query_name: event.target.value })}
              />
              {error("query_name") && (
                <p className="text-destructive text-xs">{error("query_name")}</p>
              )}
            </div>
          )}
        </>
      )}
    </fieldset>
  );
}
