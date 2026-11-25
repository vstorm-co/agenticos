"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
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
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { ProbeResult } from "@/components/kb/probe-result";
import { ProbeTestButton, WhyDisabled } from "@/components/kb/probe-test-button";
import { ServiceConnectionIcon } from "@/components/kb/service-connection-icon";
import { UnverifiedSaveDialog } from "@/components/kb/unverified-save-dialog";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useSecrets } from "@/hooks";
import { useProbeGate } from "@/hooks/use-probe-gate";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";
import {
  estimateConnectionProbe,
  KEYED_STYLES,
  probeConnection,
  SERVICE_CONNECTION_STYLES,
  type ServiceConnectionInput,
  type ServiceConnectionKind,
  type ServiceConnectionPatch,
  type ServiceConnectionRecord,
  type ServiceConnectionStyle,
} from "@/lib/service-connections-api";

interface ServiceConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether the caller may register for the whole deployment - the app admin. */
  canRegisterDeploymentWide: boolean;
  /** The row being edited. Absent when registering a new one. */
  connection?: ServiceConnectionRecord;
  /** What a new row starts as, for a picker that already knows what it needs. */
  defaults?: { kind: ServiceConnectionKind; style: ServiceConnectionStyle };
  onCreate: (input: ServiceConnectionInput) => Promise<unknown>;
  onUpdate: (id: string, patch: ServiceConnectionPatch) => Promise<unknown>;
}

const FIRST_STYLE: Readonly<Record<ServiceConnectionKind, ServiceConnectionStyle>> = {
  embedding: "ollama",
  ocr: "liteparse",
};

const STYLE_LABELS: Readonly<Record<ServiceConnectionStyle, string>> = {
  ollama: "apiStyleOllama",
  openai_compatible: "apiStyleOpenAICompatible",
  liteparse: "apiStyleLiteparse",
};

const ADDRESS_EXAMPLES: Readonly<Record<ServiceConnectionStyle, string>> = {
  ollama: "ollamaAddressExample",
  openai_compatible: "openaiCompatibleAddressExample",
  liteparse: "ocrAddressExample",
};

/**
 * Register or edit one connection. The kind and the API style are chosen when it
 * is registered and fixed after: they decide how every collection on it talks to
 * the server, so a change would be a different connection.
 *
 * Editing an embedding connection's address or key can move the vector space of
 * every collection on it. Save therefore waits for a test of exactly those
 * values - or for a confirmed save without one.
 */
export function ServiceConnectionDialog({
  open,
  onOpenChange,
  canRegisterDeploymentWide,
  connection,
  defaults,
  onCreate,
  onUpdate,
}: ServiceConnectionDialogProps) {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const { secrets } = useSecrets();
  const editing = connection !== undefined;
  const [name, setName] = useState(connection?.name ?? "");
  const [kind, setKind] = useState<ServiceConnectionKind>(
    connection?.kind ?? defaults?.kind ?? "embedding",
  );
  const [style, setStyle] = useState<ServiceConnectionStyle>(
    connection?.provider ?? defaults?.style ?? FIRST_STYLE.embedding,
  );
  const [baseUrl, setBaseUrl] = useState(connection?.base_url ?? "");
  const [secretId, setSecretId] = useState<string | null>(connection?.secret_id ?? null);
  const [deploymentWide, setDeploymentWide] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const deploymentOwned = editing ? connection.organization_id === null : deploymentWide;
  const keyed = KEYED_STYLES.has(style) && !deploymentOwned;
  const keys = secrets.filter((secret) => secret.purpose === "openai_compatible");

  const trimmedUrl = baseUrl.trim();
  const addressChanged = editing && trimmedUrl !== connection.base_url;
  const keyChanged = editing && keyed && secretId !== null && secretId !== connection.secret_id;
  // Only an embedding connection can move a vector space; renaming or pausing
  // one, or editing an OCR address, asks for no test.
  const needsTest = editing && kind === "embedding" && (addressChanged || keyChanged);

  const gate = useProbeGate({ base_url: trimmedUrl, secret_id: secretId });
  const { data: estimate, error: estimateError } = useQuery({
    queryKey: qk.serviceConnections.probeEstimate(connection?.id ?? ""),
    queryFn: () => estimateConnectionProbe(connection?.id ?? ""),
    enabled: open && needsTest,
  });

  const close = () => {
    if (!editing) {
      setName("");
      setKind(defaults?.kind ?? "embedding");
      setStyle(defaults?.style ?? FIRST_STYLE.embedding);
      setBaseUrl("");
      setSecretId(null);
      setDeploymentWide(false);
    }
    setErrors({});
    onOpenChange(false);
  };

  const fail = (error: unknown) => {
    const failure = submitFailure(
      error,
      { fields: ["name", "base_url", "kind", "provider", "secret_id", "probe_token"] },
      tErrors,
    );
    setErrors(failure.fields);
    if (failure.toast) toast.error(failure.toast);
  };

  const runTest = async () => {
    if (!connection) return;
    setErrors({});
    try {
      await gate.test(() =>
        probeConnection(connection.id, {
          ...(addressChanged ? { base_url: trimmedUrl } : {}),
          ...(keyChanged && secretId !== null ? { secret_id: secretId } : {}),
        }),
      );
    } catch (error) {
      fail(error);
    }
  };

  const changes = (): ServiceConnectionPatch => ({
    ...(connection && name.trim() !== connection.name ? { name: name.trim() } : {}),
    ...(addressChanged ? { base_url: trimmedUrl } : {}),
    ...(keyChanged && secretId !== null ? { secret_id: secretId } : {}),
  });

  const submit = async (extra: ServiceConnectionPatch = {}) => {
    setSaving(true);
    try {
      if (connection) {
        await onUpdate(connection.id, { ...changes(), ...extra });
      } else {
        await onCreate({
          name: name.trim(),
          kind,
          provider: style,
          base_url: trimmedUrl,
          ...(deploymentWide ? { deployment_wide: true } : {}),
          ...(keyed && secretId !== null ? { secret_id: secretId } : {}),
        });
      }
      close();
    } catch (error) {
      fail(error);
    } finally {
      setSaving(false);
    }
  };

  const unchanged = editing && Object.keys(changes()).length === 0;
  const blocked = needsTest && gate.token === null;
  // What the disabled Save or Register says on hover; an unchanged form needs no reason.
  const submitBlockedBy =
    name.trim() === "" || trimmedUrl === ""
      ? t("blockedMissingSettings")
      : unchanged
        ? null
        : blocked
          ? t("blockedRunTest")
          : null;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{editing ? t("editServer") : t("addServer")}</DialogTitle>
          <DialogDescription>{t("serviceConnectionsHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField label={t("name")} htmlFor="service-connection-name" error={errors.name}>
            <Input
              id="service-connection-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </FormField>
          <div className="space-y-1.5">
            <Label htmlFor="service-connection-kind">{t("serviceConnectionKind")}</Label>
            <Select
              value={kind}
              disabled={editing || defaults !== undefined}
              onValueChange={(next) => {
                const nextKind = next as ServiceConnectionKind;
                setKind(nextKind);
                setStyle(FIRST_STYLE[nextKind]);
                setSecretId(null);
              }}
            >
              <SelectTrigger id="service-connection-kind" aria-invalid={errors.kind !== undefined}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="embedding">
                  <span className="flex items-center gap-2">
                    <ServiceConnectionIcon kind="embedding" className="h-4 w-4" />
                    {t("embeddingServer")}
                  </span>
                </SelectItem>
                <SelectItem value="ocr">
                  <span className="flex items-center gap-2">
                    <ServiceConnectionIcon kind="ocr" className="h-4 w-4" />
                    {t("ocrServer")}
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
            {errors.kind && <p className="text-destructive text-xs">{errors.kind}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="service-connection-style">{t("apiStyle")}</Label>
            <Select
              value={style}
              disabled={editing || defaults !== undefined}
              onValueChange={(next) => {
                setStyle(next as ServiceConnectionStyle);
                setSecretId(null);
              }}
            >
              <SelectTrigger
                id="service-connection-style"
                aria-invalid={errors.provider !== undefined}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SERVICE_CONNECTION_STYLES[kind].map((option) => (
                  <SelectItem key={option} value={option}>
                    {t(STYLE_LABELS[option])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.provider && <p className="text-destructive text-xs">{errors.provider}</p>}
          </div>
          <FormField
            label={t("address")}
            htmlFor="service-connection-url"
            description={t("addressHint")}
            error={errors.base_url}
          >
            <Input
              id="service-connection-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={t(ADDRESS_EXAMPLES[style])}
            />
          </FormField>
          {KEYED_STYLES.has(style) &&
            (keyed ? (
              <div className="space-y-1.5">
                <Label htmlFor="service-connection-key">{t("connectionKey")}</Label>
                <Select value={secretId ?? ""} onValueChange={setSecretId}>
                  <SelectTrigger
                    id="service-connection-key"
                    aria-invalid={errors.secret_id !== undefined}
                  >
                    <SelectValue placeholder={t("chooseKey")} />
                  </SelectTrigger>
                  <SelectContent>
                    {keys.map((secret) => (
                      <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                        <ProviderRow
                          provider="openai_compatible"
                          name={secret.name}
                          hint={secret.hint}
                        />
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">{t("connectionKeyHint")}</p>
                {errors.secret_id && <p className="text-destructive text-xs">{errors.secret_id}</p>}
                <InlineSecret
                  kind="api_key"
                  purpose="openai_compatible"
                  suggestedName={t("embeddingsKeyName", {
                    provider: t("apiStyleOpenAICompatible"),
                  })}
                  onCreated={setSecretId}
                />
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">{t("deploymentWideKeyless")}</p>
            ))}
          {!editing && canRegisterDeploymentWide && (
            <div className="flex items-start justify-between gap-4">
              <div>
                <Label htmlFor="service-connection-deployment-wide">{t("deploymentWide")}</Label>
                <p className="text-muted-foreground mt-0.5 text-xs">{t("deploymentWideHint")}</p>
              </div>
              <Switch
                id="service-connection-deployment-wide"
                checked={deploymentWide}
                onCheckedChange={(next) => {
                  setDeploymentWide(next);
                  if (next) setSecretId(null);
                }}
              />
            </div>
          )}
          {needsTest && (
            <div className="space-y-2">
              <p className="text-muted-foreground text-xs">{t("testRetryNote")}</p>
              {gate.result && <ProbeResult result={gate.result} />}
              {gate.status === "failed" && (
                <p className="text-muted-foreground text-xs">{t("probeFailedAdvice")}</p>
              )}
              {errors.probe_token && (
                <p className="text-destructive text-xs">{errors.probe_token}</p>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          {needsTest && (
            <div className="mr-auto flex flex-wrap items-center gap-2">
              <ProbeTestButton
                status={gate.status}
                disabled={saving || estimate === undefined}
                onClick={runTest}
              />
              {estimate ? (
                <span className="text-muted-foreground text-xs">
                  {t("testCost", { count: estimate.calls })}
                </span>
              ) : estimateError ? (
                <span className="text-destructive text-xs">
                  {getErrorMessage(estimateError, tErrors, t("testCostUnavailable"))}
                </span>
              ) : null}
            </div>
          )}
          <Button type="button" variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          {needsTest && (
            <Button
              type="button"
              variant="ghost"
              disabled={saving || name.trim() === "" || trimmedUrl === ""}
              onClick={() => setConfirming(true)}
            >
              {t("saveWithoutTest")}
            </Button>
          )}
          <WhyDisabled reason={saving ? null : submitBlockedBy}>
            <Button
              type="button"
              onClick={() =>
                submit(needsTest && gate.token !== null ? { probe_token: gate.token } : {})
              }
              disabled={saving || blocked || unchanged || name.trim() === "" || trimmedUrl === ""}
            >
              {editing
                ? saving
                  ? t("saving")
                  : t("save")
                : saving
                  ? t("registering")
                  : t("register")}
            </Button>
          </WhyDisabled>
        </DialogFooter>
        <UnverifiedSaveDialog
          open={confirming}
          onOpenChange={setConfirming}
          affected={estimate?.knowledge_bases ?? 0}
          onConfirm={() => {
            setConfirming(false);
            void submit({ unverified: true });
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
