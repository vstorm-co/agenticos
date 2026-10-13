"use client";

import { Network, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Badge, Button, DataTable, ListCard, ListCardEmpty, type Column } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { DirectoryMapping } from "@/types/directory";

interface DirectoryMappingListProps {
  mappings: DirectoryMapping[];
  isLoading: boolean;
  error: Error | null;
  /** `members:manage` and `roles:manage` both - what adding or deleting one takes. */
  canEdit: boolean;
  onAdd: () => void;
  onDelete: (mapping: DirectoryMapping) => void;
}

/** An organization's directory group mappings: which directory group becomes what here. */
export function DirectoryMappingList({
  mappings,
  isLoading,
  error,
  canEdit,
  onAdd,
  onDelete,
}: DirectoryMappingListProps) {
  const t = useTranslations("directory");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");

  const columns: Column<DirectoryMapping>[] = [
    {
      key: "external",
      className: "pl-5",
      header: t("externalGroup"),
      cell: (mapping) => (
        <span className="text-foreground font-mono text-xs break-all">
          {mapping.external_group}
        </span>
      ),
    },
    {
      key: "role",
      header: t("role"),
      cell: (mapping) => (
        <Badge variant="secondary" className="capitalize">
          {mapping.role}
        </Badge>
      ),
    },
    {
      key: "group",
      header: t("group"),
      cell: (mapping) =>
        mapping.group_id === null ? (
          <span className="text-muted-foreground text-sm">{t("noGroup")}</span>
        ) : (
          // The name is resolved by the server; a group it could not name is shown by id.
          <span className="text-sm">{mapping.group_name ?? mapping.group_id}</span>
        ),
    },
  ];
  if (canEdit) {
    columns.push({
      key: "actions",
      header: "",
      align: "right",
      className: "w-0 pr-5",
      cell: (mapping) => (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-destructive"
          onClick={() => onDelete(mapping)}
          aria-label={tc("removeNamed", { name: mapping.external_group })}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      ),
    });
  }

  return (
    <ListCard
      title={t("listTitle")}
      counted={isLoading || error ? null : t("mappingCount", { count: mappings.length })}
      contentClassName="p-0"
      controls={
        canEdit ? (
          <Button size="sm" onClick={onAdd} data-tour="org-directory-new">
            <Plus className="h-4 w-4" />
            {t("addMapping")}
          </Button>
        ) : null
      }
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
      ) : !isLoading && mappings.length === 0 ? (
        <ListCardEmpty
          icon={Network}
          title={t("emptyTitle")}
          description={t("emptyBody")}
          cta={canEdit ? { label: t("addMapping"), onClick: onAdd } : undefined}
        />
      ) : (
        <DataTable<DirectoryMapping>
          columns={columns}
          rows={mappings}
          loading={isLoading}
          skeletonRows={3}
          getRowKey={(mapping) => mapping.id}
          className="rounded-none border-0 bg-transparent"
        />
      )}
    </ListCard>
  );
}
