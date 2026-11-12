"use client";

import { useMemo, useState } from "react";
import { KeyRound, Plus, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ApiKeyCard, STATUS_VARIANT } from "@/components/settings/api-key-card";
import { CreateApiKeyDialog } from "@/components/settings/create-api-key-dialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  Pager,
  SearchInput,
  useListControls,
  type Column,
} from "@/components/ui";
import { useApiKeys, usePermissions } from "@/hooks";
import { formatDate } from "@/lib/utils";
import type { ApiKey } from "@/types/api-keys";
import { Perm } from "@/types/permissions";

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
  const { keys, isLoading, error, refetch, catalog, catalogError, retryCatalog, create, revoke } =
    useApiKeys({ canCreate });
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const ordered = useMemo(
    () => [...keys].sort((a, b) => Number(a.status !== "active") - Number(b.status !== "active")),
    [keys],
  );
  const list = useListControls({
    items: ordered,
    pageSize: 10,
    matches: (key, query) =>
      `${key.name} ${key.prefix} ${key.issuer_email}`.toLowerCase().includes(query),
  });

  const columns: Column<ApiKey>[] = [
    {
      key: "name",
      header: t("name"),
      cell: (key) => (
        <div className="min-w-0">
          <p className="text-foreground text-sm font-medium [overflow-wrap:anywhere]">{key.name}</p>
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
            cell: (key: ApiKey) => (
              <span className="text-xs [overflow-wrap:anywhere]">{key.issuer_email}</span>
            ),
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
    <section
      className="bg-card border-foreground/[0.07] shadow-card flex min-h-0 flex-col rounded-2xl border"
      data-tour="api-keys"
    >
      <header className="border-foreground/[0.06] flex flex-col items-start justify-between gap-3 border-b px-5 py-4 sm:flex-row sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="space-y-1">
            <h2 className="text-foreground text-sm font-semibold">{t("title")}</h2>
            <p className="text-muted-foreground max-w-2xl text-xs leading-5">{t("why")}</p>
          </div>
        </div>
        {canCreate && catalog && (
          <Button size="sm" className="w-full sm:w-auto" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            {t("createTitle")}
          </Button>
        )}
      </header>
      {canCreate && catalogError && (
        <div className="px-4 pt-4 sm:px-6">
          <ErrorState
            title={t("couldNotLoadScopes")}
            cta={{ label: tc("retry"), onClick: () => void retryCatalog() }}
          />
        </div>
      )}
      {!isLoading && !error && keys.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title={t("emptyTitle")}
          description={t("emptyWhy")}
          className="flex-1 border-0 bg-transparent"
        />
      ) : (
        <div className="space-y-4 p-4 sm:p-6">
          {keys.length > 0 && !error && (
            <SearchInput
              value={list.query}
              onChange={list.setQuery}
              placeholder={t("search")}
              className="w-full sm:max-w-sm"
            />
          )}
          {error ? (
            <ErrorState
              title={t("couldNotLoad")}
              cta={{ label: tc("retry"), onClick: () => void refetch() }}
            />
          ) : isLoading ? (
            <LoadingState variant="pending" />
          ) : list.visible.length === 0 ? (
            <EmptyState
              icon={Search}
              title={t("noMatches")}
              description={t("searchHint")}
              cta={{ label: t("clearSearch"), onClick: () => list.setQuery("") }}
              className="border-0"
            />
          ) : (
            <>
              <DataTable
                className="hidden rounded-none border-0 md:block"
                columns={columns}
                rows={list.visible}
                getRowKey={(key) => key.id}
              />
              <div className="md:hidden">
                <ul className="space-y-3">
                  {list.visible.map((key) => (
                    <ApiKeyCard
                      key={key.id}
                      apiKey={key}
                      manages={manages}
                      onRevoke={setRevoking}
                    />
                  ))}
                </ul>
              </div>
              <Pager
                page={list.page}
                pageCount={list.pageCount}
                matched={list.matched}
                total={list.total}
                onPage={list.setPage}
                counted={t("keyCount", { count: list.total })}
              />
            </>
          )}
        </div>
      )}
      {catalog && (
        <CreateApiKeyDialog
          open={creating}
          onOpenChange={(open) => {
            setCreating(open);
            if (!open) create.reset();
          }}
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
          onConfirm={() => revoke.mutate(revoking.id, { onSuccess: () => setRevoking(null) })}
        />
      )}
    </section>
  );
}
