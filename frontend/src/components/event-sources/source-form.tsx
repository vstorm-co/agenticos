"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useEventSourceWrites } from "@/hooks/use-event-sources";
import type {
  EventSource,
  EventSourceCreated,
  SourceAuth,
  SourceCredentials,
  SourceProvider,
} from "@/lib/event-sources-api";

export const SOURCE_PROVIDERS: SourceProvider[] = [
  "webhook",
  "github",
  "linear",
  "hubspot",
  "zendesk",
];

export function SourceCredentialsFields({
  method,
  value,
  onChange,
  generate = false,
}: {
  generate?: boolean;
  method: SourceAuth["method"];
  value: SourceCredentials;
  onChange: (value: SourceCredentials) => void;
}) {
  const t = useTranslations("eventSources");
  return (
    <div className="space-y-3">
      {method === "basic" ? (
        <>
          <Label htmlFor="source-username">{t("username")}</Label>
          <Input
            id="source-username"
            autoComplete="off"
            value={value.username ?? ""}
            onChange={(e) => onChange({ ...value, username: e.target.value })}
          />
          <Label htmlFor="source-password">{t("password")}</Label>
          <Input
            id="source-password"
            type="password"
            autoComplete="new-password"
            value={value.password ?? ""}
            onChange={(e) => onChange({ ...value, password: e.target.value })}
          />
        </>
      ) : (
        <>
          <Label htmlFor="source-secret">{t("secret")}</Label>
          <Input
            id="source-secret"
            type="password"
            autoComplete="new-password"
            value={value.secret ?? ""}
            onChange={(e) => onChange({ secret: e.target.value })}
          />
          <p className="text-muted-foreground text-xs">
            {generate ? t("secretHelp") : t("credentialHelp")}
          </p>
        </>
      )}
    </div>
  );
}

export function SourceForm({
  source,
  onSaved,
  onCancel,
}: {
  source?: EventSource;
  onSaved: (source: EventSourceCreated) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("eventSources");
  const writes = useEventSourceWrites();
  const [name, setName] = useState(source?.name ?? "");
  const [provider, setProvider] = useState<SourceProvider>(source?.provider ?? "webhook");
  const [auth, setAuth] = useState<SourceAuth>(
    source?.auth ?? {
      method: "hmac",
      header_name: "X-Webhook-Signature",
      signature_prefix: "sha256=",
      encoding: "hex",
    },
  );
  const [visibility, setVisibility] = useState<"private" | "org">(source?.visibility ?? "private");
  const [deliveryHeader, setDeliveryHeader] = useState(source?.delivery_id_header ?? "");
  const [credentials, setCredentials] = useState<SourceCredentials>({});
  const pending = writes.create.isPending || writes.update.isPending;
  const supportsCustomDeliveryId = auth.method !== "standard_webhooks";
  const save = () => {
    const input = {
      name: name.trim(),
      auth,
      visibility,
      delivery_id_header: supportsCustomDeliveryId ? deliveryHeader.trim() || null : null,
    };
    if (source)
      writes.update.mutate(
        {
          id: source.id,
          input: { ...input, ...(auth.method !== source.auth.method ? { credentials } : {}) },
        },
        { onSuccess: onSaved },
      );
    else writes.create.mutate({ ...input, provider, credentials }, { onSuccess: onSaved });
  };
  return (
    <div className="space-y-4" data-tour="event-source-form">
      <div className="space-y-1.5">
        <Label htmlFor="source-name">{t("name")}</Label>
        <Input id="source-name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="source-provider">{t("provider")}</Label>
        <Select
          value={provider}
          disabled={!!source}
          onValueChange={(value) => {
            setProvider(value as SourceProvider);
            setAuth(
              value === "webhook"
                ? {
                    method: "hmac",
                    header_name: "X-Webhook-Signature",
                    signature_prefix: "sha256=",
                    encoding: "hex",
                  }
                : { method: "provider" },
            );
            setCredentials({});
          }}
        >
          <SelectTrigger id="source-provider">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOURCE_PROVIDERS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`providers.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("manualSetup")}</p>
      </div>
      {provider === "webhook" && <SourceAuthFields auth={auth} onChange={setAuth} />}
      {(!source || source.auth.method !== auth.method) && (
        <SourceCredentialsFields
          method={auth.method}
          generate={!source && auth.method !== "provider"}
          value={credentials}
          onChange={setCredentials}
        />
      )}
      <div className="space-y-1.5">
        <Label htmlFor="source-visibility">{t("visibility")}</Label>
        <Select
          value={visibility}
          onValueChange={(value) => setVisibility(value as "private" | "org")}
        >
          <SelectTrigger id="source-visibility">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="private">{t("private")}</SelectItem>
            <SelectItem value="org">{t("organization")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {supportsCustomDeliveryId && (
        <div className="space-y-1.5">
          <Label htmlFor="source-delivery-header">{t("deliveryHeader")}</Label>
          <Input
            id="source-delivery-header"
            value={deliveryHeader}
            onChange={(e) => setDeliveryHeader(e.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("deliveryHelp")}</p>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button
          type="button"
          disabled={
            !name.trim() ||
            pending ||
            (((!source && auth.method === "provider") ||
              (source && source.auth.method !== auth.method && auth.method !== "basic")) &&
              !credentials.secret) ||
            ((!source || source.auth.method !== auth.method) &&
              auth.method === "basic" &&
              (!credentials.username || !credentials.password))
          }
          onClick={save}
        >
          {source ? t("save") : t("create")}
        </Button>
      </div>
    </div>
  );
}

function SourceAuthFields({
  auth,
  onChange,
}: {
  auth: SourceAuth;
  onChange: (auth: SourceAuth) => void;
}) {
  const t = useTranslations("eventSources");
  return (
    <div className="space-y-3">
      <Label htmlFor="source-auth">{t("authentication")}</Label>
      <Select
        value={auth.method}
        onValueChange={(value) =>
          onChange({
            method: value as SourceAuth["method"],
            ...(value === "hmac"
              ? {
                  header_name: "X-Webhook-Signature",
                  signature_prefix: "sha256=",
                  encoding: "hex" as const,
                }
              : value === "api_key"
                ? { header_name: "X-API-Key", signature_prefix: "" }
                : {}),
          })
        }
      >
        <SelectTrigger id="source-auth">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(["hmac", "basic", "api_key", "standard_webhooks"] as const).map((value) => (
            <SelectItem key={value} value={value}>
              {t(`auth.${value}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {(auth.method === "hmac" || auth.method === "api_key") && (
        <>
          <Label htmlFor="source-header">{t("header")}</Label>
          <Input
            id="source-header"
            value={auth.header_name ?? ""}
            onChange={(e) => onChange({ ...auth, header_name: e.target.value })}
          />
          <Label htmlFor="source-prefix">{t("prefix")}</Label>
          <Input
            id="source-prefix"
            value={auth.signature_prefix ?? ""}
            onChange={(e) => onChange({ ...auth, signature_prefix: e.target.value })}
          />
        </>
      )}
      {auth.method === "hmac" && (
        <>
          <Label htmlFor="source-encoding">{t("encoding")}</Label>
          <Select
            value={auth.encoding ?? "hex"}
            onValueChange={(value) =>
              onChange({ ...auth, encoding: value as SourceAuth["encoding"] })
            }
          >
            <SelectTrigger id="source-encoding">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["hex", "base64", "base64url"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2">
            <Switch
              id="source-legacy"
              checked={auth.legacy ?? false}
              onCheckedChange={(legacy) => onChange({ ...auth, legacy })}
            />
            <Label htmlFor="source-legacy">{t("legacy")}</Label>
          </div>
        </>
      )}
      {auth.method === "standard_webhooks" && (
        <p className="text-muted-foreground text-xs">{t("standardHelp")}</p>
      )}
    </div>
  );
}
