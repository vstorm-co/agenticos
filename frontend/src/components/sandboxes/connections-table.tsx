"use client";

import { useMemo } from "react";
import { Box, Cloud, Pencil, Star, Trash2 } from "lucide-react";

import { Badge, Button, DataTable, type Column } from "@/components/ui";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface ConnectionsTableProps {
  connections: readonly SandboxConnectionRecord[];
  onEdit: (connection: SandboxConnectionRecord) => void;
  onInspect: (connection: SandboxConnectionRecord) => void;
  onDelete: (connection: SandboxConnectionRecord) => void;
}

/** What kind of host this is, in words and an icon rather than a stored string. */
function kindLabel(kind: string, t: (key: string) => string): string {
  return kind === "daytona" ? t("daytonaCloud") : t("containerService");
}

/**
 * Where a connection points, for someone comparing rows.
 *
 * Daytona has no address of ours to show, and printing an empty cell reads as a
 * misconfiguration rather than as the answer.
 */
function addressLabel(connection: SandboxConnectionRecord): string {
  if (connection.kind === "daytona") return "their API";
  return connection.base_url ?? "—";
}

/**
 * The hosts this organization's agents can be given a workspace on.
 *
 * A table because every question asked here compares rows: which is the default,
 * which is switched off, which has a credential attached. The credential itself
 * is never a column - only whether one is there, which is the part an operator
 * can act on.
 */
export function ConnectionsTable({
  connections,
  onEdit,
  onInspect,
  onDelete,
}: ConnectionsTableProps) {
  const t = useTranslations("sandboxes.table");
  const tc = useTranslations("common");

  const rows = useMemo(() => [...connections], [connections]);

  const columns = useMemo<Column<SandboxConnectionRecord>[]>(
    () => [
      {
        key: "name",
        header: t("name"),
        sortable: true,
        sortValue: (connection) => connection.name,
        cell: (connection) => (
          <div className="flex items-center gap-2">
            {connection.kind === "daytona" ? (
              <Cloud className="text-muted-foreground h-4 w-4" aria-hidden />
            ) : (
              <Box className="text-muted-foreground h-4 w-4" aria-hidden />
            )}
            <span className="font-medium">{connection.name}</span>
            {connection.is_default && (
              <Badge variant="secondary" className="gap-1">
                <Star className="h-3 w-3" aria-hidden />
                {t("default")}
              </Badge>
            )}
            {!connection.is_active && <Badge variant="outline">{t("off")}</Badge>}
          </div>
        ),
      },
      {
        key: "kind",
        header: t("kind"),
        cell: (connection) => (
          <span className="text-muted-foreground">{kindLabel(connection.kind, t)}</span>
        ),
      },
      {
        key: "address",
        header: t("address"),
        cell: (connection) => (
          <span className="text-muted-foreground font-mono text-xs">
            {addressLabel(connection)}
          </span>
        ),
      },
      {
        key: "credential",
        header: t("credential"),
        cell: (connection) =>
          connection.secret_id === null ? (
            // Not cosmetic: a connection with no credential resolves and
            // then refuses every session, which surfaces inside somebody's
            // conversation rather than here.
            <Badge variant="destructive">{t("missing")}</Badge>
          ) : (
            <Badge variant="secondary">{t("inTheVault")}</Badge>
          ),
      },
      {
        key: "defaultRuntime",
        header: t("defaultRuntime"),
        cell: (connection) => (
          <span className="text-muted-foreground font-mono text-xs">
            {connection.default_runtime ?? t("serviceSOwn")}
          </span>
        ),
      },
      {
        key: "actions",
        header: t("actions"),
        align: "right",
        cell: (connection) => (
          <div className="flex justify-end gap-1">
            {connection.kind !== "daytona" && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onInspect(connection)}
                aria-label={t("whatNamedAllows", { name: connection.name })}
              >
                {t("whatAllows")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onEdit(connection)}
              aria-label={tc("editNamed", { name: connection.name })}
            >
              <Pencil className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDelete(connection)}
              aria-label={tc("deleteNamed", { name: connection.name })}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        ),
      },
    ],
    [t, tc, onEdit, onInspect, onDelete],
  );

  return (
    <DataTable<SandboxConnectionRecord>
      columns={columns}
      rows={rows}
      getRowKey={(connection) => connection.id}
      className="rounded-none border-0 bg-transparent"
    />
  );
}
