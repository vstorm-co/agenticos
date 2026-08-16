"use client";

import { useMemo, useState } from "react";
import { Lock, RotateCw, Trash2, Users } from "lucide-react";

import { ProviderIcon } from "@/components/vault/provider-icon";
import {
  Badge,
  Button,
  DataTable,
  EntityAvatar,
  ListCardControlsRow,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import type { Secret, SecretPurpose } from "@/types/secrets";
import { useTranslations } from "next-intl";

interface SecretsTableProps {
  secrets: readonly Secret[];
  purposes: readonly SecretPurpose[];
  canManage: boolean;
  onShare: (secret: Secret) => void;
  onRotate: (secret: Secret) => void;
  onDelete: (secret: Secret) => void;
}

/** What a key is for, in words, falling back to the stored id for a custom one. */
function purposeLabel(
  purposes: readonly SecretPurpose[],
  purpose: string | undefined,
  t: (key: string) => string,
): string {
  if (!purpose || purpose === "custom") return t("customService");
  return purposes.find((entry) => entry.id === purpose)?.label ?? purpose;
}

/** The stored purpose as one filterable id, `custom` for a missing one. */
function purposeId(secret: Secret): string {
  return secret.purpose && secret.purpose !== "custom" ? secret.purpose : "custom";
}

/**
 * How far one key reaches, in the words the sharing panel uses.
 *
 * Visibility and share count are two different facts and the listing shows
 * both: an organization-wide key reaches everybody whatever the grants say, and
 * a private key shared with four people is a different thing from a private key
 * shared with nobody. Collapsing them into one number is how somebody deletes
 * the wrong key.
 */
function reach(
  secret: Secret,
  t: (key: string, values?: Record<string, number>) => string,
): { label: string; detail: string | null } {
  const shared = secret.shared_with ?? 0;
  const sharedWith = shared === 0 ? null : t("sharedWithPeople", { count: shared });
  if (secret.visibility === "private") return { label: t("visibilityPrivate"), detail: sharedWith };
  if (secret.visibility === "team") return { label: t("visibilityTeam"), detail: sharedWith };
  return { label: t("visibilityOrg"), detail: null };
}

/**
 * The organization's keys, one row each.
 *
 * A table rather than cards because every question asked here is a comparison
 * across rows - which of these is private, who added that one, what is holding
 * up which agent - and cards put the answers in different places on every row.
 */
export function SecretsTable({
  secrets,
  purposes,
  canManage,
  onShare,
  onRotate,
  onDelete,
}: SecretsTableProps) {
  const t = useTranslations("vault");
  const tc = useTranslations("common");

  // The service narrowing, in the controls strip like every list's filters -
  // never a second header row under the columns (the rejected pattern).
  const [purpose, setPurpose] = useState("all");
  const rows = useMemo(
    () =>
      purpose === "all" ? [...secrets] : secrets.filter((secret) => purposeId(secret) === purpose),
    [secrets, purpose],
  );

  const purposeOptions = useMemo(() => {
    const present = new Map<string, string>();
    for (const secret of secrets) {
      const id = purposeId(secret);
      if (!present.has(id)) present.set(id, purposeLabel(purposes, secret.purpose, t));
    }
    return [...present]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [secrets, purposes, t]);

  const columns = useMemo<Column<Secret>[]>(() => {
    const cols: Column<Secret>[] = [
      {
        key: "key",
        header: t("key"),
        className: "pl-5",
        sortable: true,
        sortValue: (secret) => secret.name,
        cell: (secret) => (
          <div className="flex items-center gap-3">
            {/* The service's own mark. A vault is scanned, not read:
                fifty rows of identical text is a list nobody finds
                anything in, and the logo is what the eye lands on. */}
            <ProviderIcon provider={secret.purpose ?? "custom"} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{secret.name}</p>
              <p className="text-muted-foreground font-mono text-xs">····{secret.hint}</p>
            </div>
          </div>
        ),
      },
      {
        key: "for",
        header: t("for"),
        cell: (secret) => (
          <span className="text-muted-foreground text-sm">
            {purposeLabel(purposes, secret.purpose, t)}
          </span>
        ),
      },
      {
        key: "access",
        header: t("access"),
        cell: (secret) => {
          const access = reach(secret, t);
          return (
            <div className="flex flex-col items-start gap-1">
              <Badge variant={secret.visibility === "private" ? "outline" : "secondary"}>
                {secret.visibility === "private" && <Lock className="mr-1 h-3 w-3" />}
                {access.label}
              </Badge>
              {access.detail && (
                <span className="text-muted-foreground text-xs">{access.detail}</span>
              )}
            </div>
          );
        },
      },
      {
        key: "addedBy",
        header: t("addedBy"),
        sortable: true,
        sortValue: (secret) => secret.created_by_email ?? null,
        cell: (secret) =>
          secret.created_by_email ? (
            <div className="flex items-center gap-2">
              <EntityAvatar
                seed={secret.created_by_email}
                name={secret.created_by_email}
                imageSrc={secret.created_by_avatar_url ?? undefined}
                className="h-6 w-6 text-[10px]"
                ariaHidden
              />
              <span className="text-muted-foreground truncate text-xs">
                {secret.created_by_email}
              </span>
            </div>
          ) : (
            // The key outlives the person, which is itself worth seeing:
            // it is the one nobody is going to rotate.
            <span className="text-muted-foreground text-xs">{t("noLongerHere")}</span>
          ),
      },
      {
        key: "usedBy",
        header: t("usedBy"),
        className: canManage ? undefined : "pr-5",
        cell: (secret) => {
          const used = secret.used_by ?? [];
          return (
            <span className="text-muted-foreground text-xs">
              {used.length === 0 ? t("notUsedYet") : used.map((usage) => usage.name).join(", ")}
            </span>
          );
        },
      },
    ];

    if (canManage) {
      cols.push({
        key: "actions",
        header: t("actions"),
        align: "right",
        className: "w-32 pr-5",
        cell: (secret) => (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("manageAccessTo", { name: secret.name })}
              onClick={() => onShare(secret)}
            >
              <Users className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("rotateNamed", { name: secret.name })}
              onClick={() => onRotate(secret)}
            >
              <RotateCw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={tc("deleteNamed", { name: secret.name })}
              onClick={() => onDelete(secret)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ),
      });
    }

    return cols;
  }, [purposes, canManage, onShare, onRotate, onDelete, t, tc]);

  return (
    <>
      <ListCardControlsRow>
        <Select value={purpose} onValueChange={setPurpose}>
          <SelectTrigger className="h-8 w-[200px]" aria-label={t("filterByService")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("anyService")}</SelectItem>
            {purposeOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </ListCardControlsRow>
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(secret) => secret.id}
        className="rounded-none border-0 bg-transparent"
      />
    </>
  );
}
