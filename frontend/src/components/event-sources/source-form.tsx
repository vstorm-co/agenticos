"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
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
  Switch,
} from "@/components/ui";
import { useEventSourceWrites } from "@/hooks/use-event-sources";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
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
          <FormField htmlFor="source-username" label={t("username")}>
            <Input
              autoComplete="off"
              value={value.username ?? ""}
              onChange={(e) => onChange({ ...value, username: e.target.value })}
            />
          </FormField>
          <FormField htmlFor="source-password" label={t("password")}>
            <Input
              type="password"
              autoComplete="new-password"
              value={value.password ?? ""}
              onChange={(e) => onChange({ ...value, password: e.target.value })}
            />
          </FormField>
        </>
      ) : (
        <FormField
          htmlFor="source-secret"
          label={t("secret")}
          description={generate ? t("secretHelp") : t("credentialHelp")}
        >
          <Input
            type="password"
            autoComplete="new-password"
            value={value.secret ?? ""}
            onChange={(e) => onChange({ secret: e.target.value })}
          />
        </FormField>
      )}
    </div>
  );
}

interface SourceFormProps {
  source?: EventSource;
  onSaved: (source: EventSourceCreated) => void;
  onCancel: () => void;
}

export function SourceForm({ source, onSaved, onCancel }: SourceFormProps) {
  const t = useTranslations("eventSources");
  const common = useTranslations("common");
  const writes = useEventSourceWrites();
  const pending = writes.create.isPending || writes.update.isPending;
  const formId = useId();
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
  const supportsCustomDeliveryId = auth.method !== "standard_webhooks";
  const changesAuth = !!source && source.auth.method !== auth.method;
  const needsCredentials = !source || changesAuth;
  const hasCredentials =
    auth.method === "basic"
      ? !!credentials.username && !!credentials.password
      : !!credentials.secret;
  const canSave =
    !!name.trim() &&
    (!(changesAuth || (!source && (auth.method === "provider" || auth.method === "basic"))) ||
      hasCredentials);
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
          input: { ...input, ...(changesAuth ? { credentials } : {}) },
        },
        { onSuccess: onSaved },
      );
    else writes.create.mutate({ ...input, provider, credentials }, { onSuccess: onSaved });
  };
  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onCancel()}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)} dismissible={!pending}>
        <DialogHeader>
          <DialogTitle>
            {source ? common("editNamed", { name: source.name }) : t("createNew")}
          </DialogTitle>
          <DialogDescription>{t("manualSetup")}</DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          <form
            id={formId}
            data-tour="event-source-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (canSave && !pending) save();
            }}
          >
            <fieldset disabled={pending} className="min-w-0 space-y-4">
              <FormField htmlFor="source-name" label={t("name")}>
                <Input
                  required
                  data-initial-focus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </FormField>
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
                <FormField htmlFor="source-provider" label={t("provider")}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                </FormField>
                <SelectContent>
                  {SOURCE_PROVIDERS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`providers.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {provider === "webhook" && <SourceAuthFields auth={auth} onChange={setAuth} />}
              {needsCredentials && (
                <SourceCredentialsFields
                  method={auth.method}
                  generate={!source && auth.method !== "provider"}
                  value={credentials}
                  onChange={setCredentials}
                />
              )}
              <Select
                value={visibility}
                onValueChange={(value) => setVisibility(value as "private" | "org")}
              >
                <FormField htmlFor="source-visibility" label={t("visibility")}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                </FormField>
                <SelectContent>
                  <SelectItem value="private">{t("private")}</SelectItem>
                  <SelectItem value="org">{t("organization")}</SelectItem>
                </SelectContent>
              </Select>
              {supportsCustomDeliveryId && (
                <FormField
                  htmlFor="source-delivery-header"
                  label={t("deliveryHeader")}
                  description={t("deliveryHelp")}
                >
                  <Input
                    value={deliveryHeader}
                    onChange={(e) => setDeliveryHeader(e.target.value)}
                  />
                </FormField>
              )}
            </fieldset>
          </form>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
            {t("cancel")}
          </Button>
          <Button type="submit" form={formId} loading={pending} disabled={!canSave || pending}>
            {source ? t("save") : t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
    <div className="space-y-4">
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
        <FormField
          htmlFor="source-auth"
          label={t("authentication")}
          description={auth.method === "standard_webhooks" ? t("standardHelp") : undefined}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
        </FormField>
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
          <FormField htmlFor="source-header" label={t("header")}>
            <Input
              value={auth.header_name ?? ""}
              onChange={(e) => onChange({ ...auth, header_name: e.target.value })}
            />
          </FormField>
          <FormField htmlFor="source-prefix" label={t("prefix")}>
            <Input
              value={auth.signature_prefix ?? ""}
              onChange={(e) => onChange({ ...auth, signature_prefix: e.target.value })}
            />
          </FormField>
        </>
      )}
      {auth.method === "hmac" && (
        <>
          <Select
            value={auth.encoding ?? "hex"}
            onValueChange={(value) =>
              onChange({ ...auth, encoding: value as SourceAuth["encoding"] })
            }
          >
            <FormField htmlFor="source-encoding" label={t("encoding")}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
            </FormField>
            <SelectContent>
              {(["hex", "base64", "base64url"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FormField htmlFor="source-legacy" label={t("legacy")} layout="switch">
            <Switch
              checked={auth.legacy ?? false}
              onCheckedChange={(legacy) => onChange({ ...auth, legacy })}
            />
          </FormField>
        </>
      )}
    </div>
  );
}
