"use client";

import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button, DataTable, type Column } from "@/components/ui";
import { OriginBadge, PartitionBadge } from "@/components/memory/memory-badges";
import type { MemoryFileSummary } from "@/types/memory";

interface MemoryFileTableProps {
  files: MemoryFileSummary[];
  canEdit: boolean;
  loading: boolean;
  /** The failure to show instead of the empty state — never the two at once. */
  error?: React.ReactNode;
  empty: React.ReactNode;
  activeId: string | null;
  onOpen: (file: MemoryFileSummary) => void;
  onDelete: (file: MemoryFileSummary) => void;
}

/**
 * The memory index as a table — the rows the agent's `MEMORY.md` is derived
 * from. Origin, kind and partition are badges rather than text because each is a
 * closed set a reader scans down a column, and origin in particular is the trust
 * signal that must be legible without opening the file.
 */
export function MemoryFileTable({
  files,
  canEdit,
  loading,
  error,
  empty,
  activeId,
  onOpen,
  onDelete,
}: MemoryFileTableProps) {
  const t = useTranslations("memory");
  const tc = useTranslations("common");

  const columns = useMemo<Column<MemoryFileSummary>[]>(
    () => [
      {
        key: "name",
        header: t("colName"),
        cell: (file) => (
          <span className="text-foreground font-mono text-sm font-medium">{file.name}</span>
        ),
      },
      {
        key: "description",
        header: t("colDescription"),
        hideBelow: "md",
        cell: (file) => (
          <span className="text-muted-foreground line-clamp-1">{file.description || "—"}</span>
        ),
      },
      {
        key: "origin",
        header: t("colOrigin"),
        cell: (file) => <OriginBadge origin={file.origin} />,
      },
      {
        key: "kind",
        header: t("colKind"),
        hideBelow: "sm",
        cell: (file) => <Badge variant="outline">{file.kind}</Badge>,
      },
      {
        key: "partition",
        header: t("colPartition"),
        hideBelow: "sm",
        cell: (file) => <PartitionBadge scopeKey={file.end_user_scope_key} />,
      },
      {
        key: "actions",
        header: "",
        align: "right",
        className: "w-0 pr-4",
        cell: (file) =>
          canEdit ? (
            <Button
              variant="ghost"
              size="icon"
              className="text-muted-foreground hover:text-destructive h-8 w-8"
              aria-label={tc("deleteNamed", { name: file.name })}
              onClick={(event) => {
                event.stopPropagation();
                onDelete(file);
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          ) : null,
      },
    ],
    [t, tc, canEdit, onDelete],
  );

  return (
    <DataTable<MemoryFileSummary>
      columns={columns}
      rows={files}
      getRowKey={(file) => file.id}
      loading={loading}
      error={error}
      empty={empty}
      onRowClick={onOpen}
      isRowActive={(file) => file.id === activeId}
    />
  );
}
