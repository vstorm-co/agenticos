"use client";

import Link from "next/link";
import { Building2, Lock, Users } from "lucide-react";
import { ResourceIcon } from "@/components/ui/resource-icon";
import { useTranslations } from "next-intl";

import {
  Badge,
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { TaskBoard } from "@/lib/tasks-api";
import type { TableListItem } from "@/types/tables";

const VISIBILITY_ICON = { org: Building2, team: Users, private: Lock } as const;

/**
 * One table in the catalog - the agents gallery's card, for a table: what it
 * is called, how much it holds, who may reach it and when it last changed.
 */
export function TableCard({ table, taskBoard }: { table: TableListItem; taskBoard?: TaskBoard }) {
  const t = useTranslations("pages.tables");
  const tasks = useTranslations("durableTasks");
  const tc = useTranslations("common");
  const VisibilityIcon = VISIBILITY_ICON[table.visibility];

  return (
    <ResourceCard className="min-h-52">
      <Link
        href={ROUTES.TABLE_DETAIL(table.id)}
        className="focus-visible:ring-ring absolute inset-0 rounded-[inherit] outline-none focus-visible:ring-2"
        aria-label={tc("openNamed", { name: table.name })}
      />
      <ResourceCardHeader className="pointer-events-none">
        <ResourceIcon kind="table" icon={table.icon} />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-foreground line-clamp-2 font-semibold break-words">{table.name}</p>
          <span
            role="img"
            aria-label={t(`visibility.${table.visibility}`)}
            title={t(`visibility.${table.visibility}`)}
            className="text-muted-foreground flex items-center gap-1.5 text-xs"
          >
            <VisibilityIcon className="size-3 shrink-0" aria-hidden />
            <span>{t(`visibility.${table.visibility}`)}</span>
          </span>
        </div>
      </ResourceCardHeader>
      <ResourceCardDescription className="pointer-events-none my-4 line-clamp-2">
        {table.description}
      </ResourceCardDescription>
      <ResourceCardFooter className="text-muted-foreground pointer-events-none border-0 pt-0 text-xs">
        {(table.archived_at !== null || !table.can_edit) && (
          <Badge variant="outline" className="font-normal">
            {table.archived_at !== null ? t("archivedBadge") : t("readOnly")}
          </Badge>
        )}
        <span>{t("cardSize", { records: table.record_count, columns: table.column_count })}</span>
        {taskBoard && (
          <span>
            {tasks(`scope.${taskBoard.scope_kind}`)}
            {taskBoard.scope_name && ` · ${taskBoard.scope_name}`}
          </span>
        )}
      </ResourceCardFooter>
    </ResourceCard>
  );
}
