"use client";

import Link from "next/link";
import { AlertTriangle, KeyRound, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { StorableSecretKind } from "@/types/secrets";

export interface SecretPickerProps {
  /** The chosen vault secret id, or null while none is. Never a value. */
  value: string | null;
  onChange: (secretId: string | null) => void;
  disabled?: boolean;
  /** Offer only secrets of this kind, where the config field needs a specific one. */
  kind?: StorableSecretKind;
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
 */
export function SecretPicker({ value, onChange, disabled, kind, error }: SecretPickerProps) {
  const t = useTranslations("workflows");
  const { secrets, isLoading } = useSecrets();
  const offered = kind === undefined ? secrets : secrets.filter((secret) => secret.kind === kind);

  const chosen = offered.find((secret) => secret.id === value);
  // An id naming no secret the caller can see - deleted, or in another scope.
  // Kept visible for the same reason the other pickers keep an orphan: it is
  // still in `config`, and a silent disappearance is a publish-time surprise.
  const orphaned = value !== null && !isLoading && chosen === undefined;

  return (
    <div className="space-y-2">
      <Label>{t("pickerSecretLabel")}</Label>
      <Select value={value ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={t("pickerSecretLabel")}>
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

      <Link
        href={ROUTES.VAULT}
        className="text-muted-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-4"
      >
        <Plus className="h-3.5 w-3.5" />
        {t("pickerSecretStore")}
      </Link>
    </div>
  );
}
