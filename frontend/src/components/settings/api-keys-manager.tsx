"use client";

import { useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { CreateApiKeyDialog } from "@/components/settings/create-api-key-dialog";
import { EmptyState, ErrorState } from "@/components/states";
import { Badge, Button, ConfirmDialog, DataTable, type Column } from "@/components/ui";
import { useApiKeys, usePermissions } from "@/hooks";
import { formatDate } from "@/lib/utils";
import type { ApiKey, ApiKeyStatus } from "@/types/api-keys";
import { Perm } from "@/types/permissions";

const STATUS_VARIANT: Record<ApiKeyStatus, "success" | "warning" | "destructive"> = {
  active: "success",
  expired: "warning",
  revoked: "destructive",
};

/**
 * The caller's organization API keys - every key in the organization for
 * somebody holding `api_keys:manage` - with the create and revoke controls.
 *
 * Creating is gated on `api_keys:create` and not rendered without it. A key is
 * never shown here, only its prefix: the create dialog is the one place the key
 * itself appears.
 */
export function ApiKeysManager() {
  const t = useTranslations("apiKeys");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { can } = usePermissions();
  const canCreate = can(Perm.apiKeysCreate);
  const manages = can(Perm.apiKeysManage);
  const { keys, isLoading, error, refetch, catalog, create, revoke } = useApiKeys({ canCreate });
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const columns: Column<ApiKey>[] = [
    {
      key: "name",
      header: t("name"),
      cell: (key) => (
        <div className="min-w-0">
          <p className="text-foreground truncate text-sm font-medium">{key.name}</p>
          <p className="text-muted-foreground font-mono text-xs">{key.prefix}…</p>
        </div>
      ),
    },
    {
      key: "scopes",
      header: t("access"),
      cell: (key) => (
        <span className="text-muted-foreground font-mono text-xs" title={key.scopes.join(", ")}>
          {t("scopeCount", { count: key.scopes.length })}
        </span>
      ),
      hideBelow: "md",
    },
    ...(manages
      ? [
          {
            key: "issuer",
            header: t("issuer"),
            cell: (key: ApiKey) => <span className="text-xs">{key.issuer_email}</span>,
            hideBelow: "lg" as const,
          },
        ]
      : []),
    {
      key: "status",
      header: t("status"),
      cell: (key) => <Badge variant={STATUS_VARIANT[key.status]}>{t(`state.${key.status}`)}</Badge>,
    },
    {
      key: "used",
      header: t("lastUsed"),
      cell: (key) => (
        <span className="text-muted-foreground text-xs">
          {key.last_used_at ? formatDate(key.last_used_at, locale) : t("never")}
        </span>
      ),
      hideBelow: "sm",
    },
    {
      key: "expires",
      header: t("expires"),
      cell: (key) => (
        <span className="text-muted-foreground text-xs">
          {key.expires_at ? formatDate(key.expires_at, locale) : t("noExpiry")}
        </span>
      ),
      hideBelow: "md",
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (key) =>
        key.status === "active" ? (
          <Button size="sm" variant="outline" onClick={() => setRevoking(key)}>
            {t("revoke")}
          </Button>
        ) : null,
    },
  ];

  return (
    <section className="border-border bg-card rounded-xl border" data-tour="api-keys">
      <header className="border-border flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-foreground text-sm font-semibold">{t("title")}</h2>
          <p className="text-muted-foreground mt-1 text-xs">{t("why")}</p>
        </div>
        {canCreate && catalog && (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            {t("createTitle")}
          </Button>
        )}
      </header>
      <div className="px-5 py-5">
        <DataTable
          columns={columns}
          rows={keys}
          getRowKey={(key) => key.id}
          loading={isLoading}
          error={
            error ? (
              <ErrorState
                title={t("couldNotLoad")}
                cta={{ label: tc("retry"), onClick: () => void refetch() }}
              />
            ) : undefined
          }
          empty={<EmptyState icon={KeyRound} title={t("emptyTitle")} description={t("emptyWhy")} />}
        />
      </div>
      {catalog && (
        <CreateApiKeyDialog
          open={creating}
          onOpenChange={setCreating}
          catalog={catalog}
          onCreate={(input) => create.mutateAsync(input)}
          busy={create.isPending}
        />
      )}
      {revoking && (
        <ConfirmDialog
          open
          onOpenChange={() => setRevoking(null)}
          title={t("revokeTitle", { name: revoking.name })}
          description={t("revokeWhy")}
          confirmLabel={t("revoke")}
          destructive
          loading={revoke.isPending}
          onConfirm={async () => {
            await revoke.mutateAsync(revoking.id);
            setRevoking(null);
          }}
        />
      )}
    </section>
  );
}
