"use client";

import type { ReactNode } from "react";
import { RotateCw, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { ProviderIcon } from "./provider-icon";
import { Badge, Button, DataTable, EntityAvatar, type Column } from "@/components/ui";
import type { Secret, SecretPurpose } from "@/types/secrets";
import type { ConnectedAccount } from "@/types/mirage";

type VaultEntry =
  | { kind: "key"; id: string; name: string; secret: Secret }
  | {
      kind: "account";
      id: string;
      name: string;
      account: ConnectedAccount;
    };

interface VaultTableProps {
  secrets: readonly Secret[];
  purposes: readonly SecretPurpose[];
  accounts?: readonly ConnectedAccount[];
  loading?: boolean;
  empty?: ReactNode;
  canManageAccount?: (account: ConnectedAccount) => boolean;
  onShare: (secret: Secret) => void;
  onRotate: (secret: Secret) => void;
  onDelete: (secret: Secret) => void;
  onReconnectAccount?: (account: ConnectedAccount) => void;
  onDisconnectAccount?: (account: ConnectedAccount) => void;
}

/** Keys and OAuth accounts share one inventory; actions still follow each entry's own authority. */
export function VaultTable({
  secrets,
  purposes,
  accounts = [],
  loading = false,
  empty,
  canManageAccount,
  onShare,
  onRotate,
  onDelete,
  onReconnectAccount,
  onDisconnectAccount,
}: VaultTableProps) {
  const t = useTranslations("vault");
  const tc = useTranslations("common");
  const ta = useTranslations("pages.vault.connectedAccounts");
  const rows: VaultEntry[] = [
    ...secrets.map((secret) => ({
      kind: "key" as const,
      id: `key:${secret.id}`,
      name: secret.name,
      secret,
    })),
    ...accounts.map((account) => ({
      kind: "account" as const,
      id: `account:${account.owner}:${account.id}`,
      name: account.email,
      account,
    })),
  ];
  const access = (row: VaultEntry) =>
    row.kind === "account"
      ? t(row.account.owner === "personal" ? "visibilityPrivate" : "visibilityOrg")
      : t(
          row.secret.visibility === "private"
            ? "visibilityPrivate"
            : row.secret.visibility === "team"
              ? "visibilityTeam"
              : "visibilityOrg",
        );
  const columns: Column<VaultEntry>[] = [
    {
      key: "name",
      header: t("name"),
      className: "w-full max-w-0 pl-5 sm:w-[30%]",
      sortable: true,
      sortValue: (row) => row.name,
      cell: (row) => (
        <div className="flex min-w-0 items-center gap-3">
          <ProviderIcon
            provider={row.kind === "key" ? (row.secret.purpose ?? "custom") : row.account.provider}
            brand={
              row.kind === "key"
                ? purposes.find((p) => p.id === row.secret.purpose)?.icon || undefined
                : "google"
            }
          />
          <div className="min-w-0 space-y-0.5">
            <p title={row.name} className="truncate text-sm font-medium">
              {row.name}
            </p>
            {row.kind === "key" ? (
              <p className="text-muted-foreground font-mono text-xs">····{row.secret.hint}</p>
            ) : (
              <p
                className={
                  row.account.needs_reconnect
                    ? "text-destructive text-xs"
                    : "text-muted-foreground text-xs"
                }
              >
                {row.account.needs_reconnect
                  ? ta("needsReconnect")
                  : ta("scopes", { count: row.account.scopes.length })}
              </p>
            )}
            <span className="text-muted-foreground text-xs sm:hidden">{access(row)}</span>
          </div>
        </div>
      ),
    },
    {
      key: "for",
      header: t("for"),
      hideBelow: "sm",
      cell: (row) => (
        <span className="text-muted-foreground text-sm">
          {row.kind === "account"
            ? t("googleAccount")
            : !row.secret.purpose || row.secret.purpose === "custom"
              ? t("customService")
              : (purposes.find((p) => p.id === row.secret.purpose)?.label ?? row.secret.purpose)}
        </span>
      ),
    },
    {
      key: "access",
      header: t("access"),
      hideBelow: "sm",
      cell: (row) => (
        <div className="flex flex-col items-start gap-1">
          <Badge
            variant={
              row.kind === "account"
                ? row.account.owner === "personal"
                  ? "outline"
                  : "secondary"
                : row.secret.visibility === "private"
                  ? "outline"
                  : "secondary"
            }
          >
            {access(row)}
          </Badge>
          {row.kind === "key" &&
            row.secret.visibility !== "org" &&
            (row.secret.shared_with ?? 0) > 0 && (
              <span className="text-muted-foreground text-xs">
                {t("sharedWithPeople", { count: row.secret.shared_with ?? 0 })}
              </span>
            )}
        </div>
      ),
    },
    {
      key: "addedBy",
      header: t("addedBy"),
      hideBelow: "lg",
      sortable: true,
      sortValue: (row) => (row.kind === "key" ? (row.secret.created_by_email ?? null) : null),
      cell: (row) =>
        row.kind === "account" ? (
          <span className="text-muted-foreground text-xs" aria-label={t("notRecorded")}>
            —
          </span>
        ) : row.secret.created_by_email ? (
          <div className="flex items-center gap-2">
            <EntityAvatar
              seed={row.secret.created_by_user_id ?? row.secret.created_by_email}
              name={row.secret.created_by_email}
              imageSrc={row.secret.created_by_avatar_url ?? undefined}
              className="size-6 text-[11px]"
              ariaHidden
            />
            <span className="text-muted-foreground truncate text-xs">
              {row.secret.created_by_email}
            </span>
          </div>
        ) : (
          <span className="text-muted-foreground text-xs">{t("noLongerHere")}</span>
        ),
    },
    {
      key: "usedBy",
      header: t("usedBy"),
      hideBelow: "lg",
      cell: (row) => (
        <span className="text-muted-foreground text-xs">
          {row.kind === "account" ? (
            <span aria-label={t("notRecorded")}>—</span>
          ) : row.secret.used_by?.length ? (
            row.secret.used_by.map((use) => use.name).join(", ")
          ) : (
            t("notUsedYet")
          )}
        </span>
      ),
    },
    {
      key: "actions",
      header: t("actions"),
      align: "right",
      className: "w-32 pr-5",
      cell: (row) =>
        row.kind === "key"
          ? row.secret.can_edit === true && (
              <div className="flex justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("manageAccessTo", { name: row.name })}
                  onClick={() => onShare(row.secret)}
                >
                  <Users className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t(
                    row.secret.kind === "openai_codex" ? "chatgptReconnectNamed" : "rotateNamed",
                    { name: row.name },
                  )}
                  onClick={() => onRotate(row.secret)}
                >
                  <RotateCw className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={tc("deleteNamed", { name: row.name })}
                  onClick={() => onDelete(row.secret)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            )
          : canManageAccount?.(row.account) && (
              <div className="flex justify-end gap-1">
                {row.account.needs_reconnect && onReconnectAccount && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={ta("reconnectNamed", { email: row.account.email })}
                    onClick={() => onReconnectAccount(row.account)}
                  >
                    <RotateCw className="size-4" />
                  </Button>
                )}
                {onDisconnectAccount && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={ta("disconnect", { email: row.account.email })}
                    onClick={() => onDisconnectAccount(row.account)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </div>
            ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      loading={loading}
      empty={empty}
      getRowKey={(row) => row.id}
      className="rounded-none border-0 bg-transparent"
    />
  );
}
