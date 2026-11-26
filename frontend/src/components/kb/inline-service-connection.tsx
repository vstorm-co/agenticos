"use client";

import { useState } from "react";
import { Plus, Server } from "lucide-react";
import { toast } from "sonner";

import { Button, Input, Label } from "@/components/ui";
import { useServiceConnections, usePermissions } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { ServiceConnectionDialog } from "@/components/kb/service-connection-dialog";
import {
  KEYED_STYLES,
  type ServiceConnectionKind,
  type ServiceConnectionStyle,
} from "@/lib/service-connections-api";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface InlineServiceConnectionProps {
  kind: ServiceConnectionKind;
  /** The catalog id the server answers for - the embedding provider, or the parser. */
  provider: ServiceConnectionStyle;
  /** Called with the new row's id once it is registered. */
  onCreated: (serviceId: string) => void;
  disabled?: boolean;
}

const INLINE_ADDRESS_EXAMPLES: Readonly<Record<ServiceConnectionKind, string>> = {
  embedding: "ollamaAddressExample",
  ocr: "ocrAddressExample",
  // Docling is a keyed style, so it opens the full dialog; this entry only completes the Record.
  document_parser: "doclingAddressExample",
};

/**
 * Register a server without leaving the picker that needs it.
 *
 * The same shortcut `InlineSecret` is for keys, for the same reason: a select
 * with nothing in it and no way to fill it is a dead end. It is not the same
 * component, because what it posts is an address rather than a credential, and
 * the permission that guards it is `connections:manage` - the one that decides
 * where an organization's requests may be sent - not `secrets:edit`.
 *
 * Checked here rather than at each caller, so a picker never renders a button
 * for a write the server would refuse; the sentence in its place says who has to
 * do it instead.
 */
export function InlineServiceConnection({
  kind,
  provider,
  onCreated,
  disabled,
}: InlineServiceConnectionProps) {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { create, update } = useServiceConnections(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  if (!can(Perm.connectionsManage)) {
    return <p className="text-muted-foreground text-xs">{t("registeringNeedsPermission")}</p>;
  }

  // A style that carries a key needs the key picker, which the full dialog has.
  if (KEYED_STYLES.has(provider)) {
    return (
      <>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("addServer")}
        </Button>
        <ServiceConnectionDialog
          open={open}
          onOpenChange={setOpen}
          canRegisterDeploymentWide={false}
          defaults={{ kind, style: provider }}
          onCreate={async (input) => {
            const created = await create(input);
            onCreated(created.id);
            return created;
          }}
          onUpdate={update}
        />
      </>
    );
  }

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Plus className="h-3.5 w-3.5" />
        {t("addServer")}
      </Button>
    );
  }

  const submit = async () => {
    setSaving(true);
    try {
      const created = await create({ name: name.trim(), kind, provider, base_url: baseUrl.trim() });
      onCreated(created.id);
      setName("");
      setBaseUrl("");
      setErrors({});
      setOpen(false);
    } catch (error) {
      const failure = submitFailure(error, { fields: ["name", "base_url"] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-border space-y-3 rounded-lg border border-dashed p-3">
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <Server className="h-3.5 w-3.5 shrink-0" />
        {t("serverOnDeploymentNetwork")}
      </p>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="space-y-1.5">
          <Label htmlFor="inline-service-connection-name" className="text-xs">
            {t("name")}
          </Label>
          <Input
            id="inline-service-connection-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={errors.name !== undefined}
          />
          {errors.name && <p className="text-destructive text-xs">{errors.name}</p>}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="inline-service-connection-url" className="text-xs">
            {t("address")}
          </Label>
          <Input
            id="inline-service-connection-url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={t(INLINE_ADDRESS_EXAMPLES[kind])}
            aria-invalid={errors.base_url !== undefined}
          />
          {errors.base_url && <p className="text-destructive text-xs">{errors.base_url}</p>}
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
          {t("cancel")}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={saving || name.trim() === "" || baseUrl.trim() === ""}
          onClick={submit}
        >
          {saving ? t("registering") : t("register")}
        </Button>
      </div>
    </div>
  );
}
