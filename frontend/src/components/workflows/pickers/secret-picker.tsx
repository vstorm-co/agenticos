"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ExternalLink, KeyRound, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { AddSecretDialog } from "@/components/vault/secret-dialog";
import {
  Badge,
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { usePermissions, useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { StorableSecretKind } from "@/types/secrets";

export interface SecretPickerProps {
  /** What the control is called: the field's own name, or the picker's when it has none. */
  label?: string;
  /** The chosen vault secret id, or null while none is. Never a value. */
  value: string | null;
  onChange: (secretId: string | null) => void;
  disabled?: boolean;
  /**
   * Offer only secrets of this kind, where the config field needs a specific one.
   * A kind name as the node catalog serves it (`x-secret-kind`), so a kind this
   * build has no type for simply offers nothing rather than everything.
   */
  kind?: StorableSecretKind | (string & {});
  /** A validation message from the property panel, shown under the control. */
  error?: string;
}

/**
 * Which vault secret a config field references.
 *
 * The vault is write-only: there is no endpoint that returns a plaintext, so this
 * picker never sees or writes a value. It writes a secret *id* into `config`, and
 * the runtime resolves it through the vault at execution time - the same
 * kind/metadata-only selection the model and connector forms already use. A field
 * that names a `kind` narrows the list to it; a mismatched stored kind is one the
 * runtime would refuse, so it is not offered.
 *
 * **New secret** stores one without leaving the editor: the vault's own form,
 * fixed to the field's kind, choosing the new secret on save. The value goes
 * from that form to the vault and nowhere else - only the id comes back.
 */
export function SecretPicker({ value, onChange, disabled, kind, error, label }: SecretPickerProps) {
  const t = useTranslations("workflows");
  const caption = label ?? t("pickerSecretLabel");
  const { secrets, kinds, isLoading, create } = useSecrets();
  const { can } = usePermissions();
  const [adding, setAdding] = useState(false);
  const offered = kind === undefined ? secrets : secrets.filter((secret) => secret.kind === kind);
  // The field's kind as this build knows it. One it has no form for offers no
  // dialog; a field naming none takes any shape, so the whole vault form opens.
  const shape = kind === undefined ? undefined : kinds.find((entry) => entry.kind === kind);
  const addable = can(Perm.secretsEdit) && (kind === undefined || shape !== undefined);

  const chosen = offered.find((secret) => secret.id === value);
  // An id naming no secret the caller can see - deleted, or in another scope.
  // Kept visible for the same reason the other pickers keep an orphan: it is
  // still in `config`, and a silent disappearance is a publish-time surprise.
  const orphaned = value !== null && !isLoading && chosen === undefined;

  return (
    <div className="space-y-2">
      <Label>{caption}</Label>
      <Select value={value ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={caption}>
          <SelectValue placeholder={t("pickerSecretPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {offered.map((secret) => (
            <SelectItem key={secret.id} value={secret.id}>
              <span className="flex items-center gap-2">
                <KeyRound className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{secret.name}</span>
                <Badge variant="outline">{secret.kind}</Badge>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {offered.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-xs">{t("pickerSecretsEmpty")}</p>
      )}
      {orphaned && (
        <p className="text-foreground/70 flex items-center gap-1.5 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {t("pickerSecretOrphaned")} <span className="font-mono break-all">{value}</span>
        </p>
      )}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}

      <div className="flex flex-wrap items-center gap-3">
        {addable && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => setAdding(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("pickerSecretNew")}
          </Button>
        )}
        <Link
          href={ROUTES.VAULT}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-4"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          {t("pickerSecretStore")}
        </Link>
      </div>
      {addable && (
        <AddSecretDialog
          open={adding}
          onOpenChange={setAdding}
          kinds={kinds}
          kind={shape?.kind}
          isPending={create.isPending}
          onSubmit={async (data) => onChange((await create.mutateAsync(data)).id)}
        />
      )}
    </div>
  );
}
