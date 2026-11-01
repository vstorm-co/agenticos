"use client";

import { useMemo } from "react";
import { Box, Cloud, Pencil, ShieldCheck, Star, Trash2 } from "lucide-react";

import { Badge, Button, DataTable, type Column } from "@/components/ui";
import { ConnectionKindIcon } from "./connection-kind-icon";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface ConnectionsTableProps {
  connections: readonly SandboxConnectionRecord[];
  onEdit: (connection: SandboxConnectionRecord) => void;
  onInspect: (connection: SandboxConnectionRecord) => void;
  onDelete: (connection: SandboxConnectionRecord) => void;
}

/** What kind of host this is, in words rather than the stored string. The mark
 * beside them is `ConnectionKindIcon`, which the dialog and the Builder draw too. */
function kindLabel(kind: string, t: (key: string) => string): string {
  if (kind === "daytona") return t("daytonaCloud");
  if (kind === "e2b") return t("e2bCloud");
  return t("containerService");
}

/**
 * Where a connection points, for someone comparing rows.
 *
 * Daytona has no address of ours to show, and printing an empty cell reads as a
 * misconfiguration rather than as the answer.
 */
function addressLabel(connection: SandboxConnectionRecord): string {
  if (connection.kind !== "docker") return "their API";
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
        // Takes what the others leave and cuts a long name short, rather than
        // pushing the actions off a phone.
        // The room the other columns leave, which they take first: they keep to
        // one line (the address used to wrap while the name sat in a sea of
        // space), and the name truncates only when the row truly runs out.
        className: "w-full max-w-0 pl-5",
        header: t("name"),
        sortable: true,
        sortValue: (connection) => connection.name,
        cell: (connection) => (
          <div className="flex min-w-0 items-center gap-2">
            {connection.kind !== "docker" ? (
              <Cloud className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
            ) : (
              <Box className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
            )}
            <span className="truncate font-medium">{connection.name}</span>
            {connection.is_default && (
              <Badge variant="secondary" className="shrink-0 gap-1">
                <Star className="h-3 w-3" aria-hidden />
                {t("default")}
              </Badge>
            )}
            {!connection.is_active && <Badge variant="outline">{t("off")}</Badge>}
          </div>
        ),
      },
      {
        // Not on a phone, where they pushed the actions off the screen; the connection's dialog has them all.
        key: "kind",
        hideBelow: "sm",
        header: t("kind"),
        cell: (connection) => (
          <span className="text-muted-foreground flex items-center gap-2 whitespace-nowrap">
            <ConnectionKindIcon kind={connection.kind} className="h-3.5 w-3.5" />
            {kindLabel(connection.kind, t)}
          </span>
        ),
      },
      {
        key: "address",
        hideBelow: "sm",
        header: t("address"),
        cell: (connection) => (
          <span className="text-muted-foreground font-mono text-xs whitespace-nowrap">
            {addressLabel(connection)}
          </span>
        ),
      },
      {
        key: "credential",
        hideBelow: "sm",
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
        hideBelow: "sm",
        header: t("defaultRuntime"),
        cell: (connection) =>
          // A runtime's name is an identifier and reads as one; "the service's
          // own" is a phrase and does not.
          connection.default_runtime ? (
            <span className="text-muted-foreground font-mono text-xs">
              {connection.default_runtime}
            </span>
          ) : (
            <span className="text-muted-foreground text-xs whitespace-nowrap">
              {t("serviceSOwn")}
            </span>
          ),
      },
      {
        key: "actions",
        className: "pr-5",
        header: t("actions"),
        align: "right",
        cell: (connection) => (
          <div className="flex justify-end gap-1">
            {connection.kind === "docker" && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onInspect(connection)}
                aria-label={t("whatNamedAllows", { name: connection.name })}
              >
                {/* An icon on a phone, where the words took the name's room. */}
                <ShieldCheck className="h-4 w-4 sm:hidden" aria-hidden />
                <span className="max-sm:hidden">{t("whatAllows")}</span>
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
