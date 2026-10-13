"use client";

import { Pencil, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Button, DataTable, ListCard, ListCardEmpty, type Column } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { Group } from "@/types/groups";

interface GroupListProps {
  groups: Group[];
  isLoading: boolean;
  error: Error | null;
  canManage: boolean;
  onCreate: () => void;
  onEdit: (group: Group) => void;
  onDelete: (group: Group) => void;
  onOpenMembers: (group: Group) => void;
}

/**
 * An organization's groups, and the way into each one's members.
 *
 * The member count opens the members for everybody - reading who is in a group
 * is what deciding to share with it takes - while renaming and deleting are
 * drawn only for a caller holding `members:manage`.
 */
export function GroupList({
  groups,
  isLoading,
  error,
  canManage,
  onCreate,
  onEdit,
  onDelete,
  onOpenMembers,
}: GroupListProps) {
  const t = useTranslations("groups");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");

  const columns: Column<Group>[] = [
    {
      key: "name",
      className: "pl-5",
      header: t("name"),
      cell: (group) => (
        <div className="min-w-0">
          <p className="text-foreground truncate text-sm font-medium">{group.name}</p>
          {group.description && (
            <p className="text-muted-foreground truncate text-xs">{group.description}</p>
          )}
        </div>
      ),
    },
    {
      key: "members",
      header: t("members"),
      cell: (group) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onOpenMembers(group)}
          aria-label={t("membersOf", { name: group.name })}
        >
          <Users className="h-4 w-4" />
          {t("memberCount", { count: group.member_count })}
        </Button>
      ),
    },
  ];
  if (canManage) {
    columns.push({
      key: "actions",
      header: "",
      align: "right",
      className: "w-0 pr-5",
      cell: (group) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onEdit(group)}
            aria-label={t("editNamed", { name: group.name })}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => onDelete(group)}
            aria-label={tc("removeNamed", { name: group.name })}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    });
  }

  return (
    <ListCard
      title={t("title")}
      counted={isLoading || error ? null : t("groupCount", { count: groups.length })}
      contentClassName="p-0"
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
      ) : !isLoading && groups.length === 0 ? (
        <ListCardEmpty
          icon={Users}
          title={t("emptyTitle")}
          description={t("emptyBody")}
          cta={canManage ? { label: t("newGroup"), onClick: onCreate } : undefined}
        />
      ) : (
        <DataTable<Group>
          columns={columns}
          rows={groups}
          loading={isLoading}
          skeletonRows={3}
          getRowKey={(group) => group.id}
          className="rounded-none border-0 bg-transparent"
        />
      )}
    </ListCard>
  );
}
