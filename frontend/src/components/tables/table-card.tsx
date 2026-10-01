"use client";

import Link from "next/link";
import { useState } from "react";
import { Building2, Lock, Table2, Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { Beam } from "@/components/ui/beam";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import type { TableListItem } from "@/types/tables";

const VISIBILITY_ICON = { org: Building2, team: Users, private: Lock } as const;

/**
 * One table in the catalog - the agents gallery's card, for a table: what it
 * is called, how much it holds, who may reach it and when it last changed.
 */
export function TableCard({ table }: { table: TableListItem }) {
  const t = useTranslations("pages.tables");
  const tc = useTranslations("common");
  const tt = useTranslations("time");
  const locale = useLocale();
  const [hovered, setHovered] = useState(false);
  const VisibilityIcon = VISIBILITY_ICON[table.visibility];
  const edited = table.updated_at ?? table.created_at;

  return (
    <Beam
      size="md"
      borderRadius={12}
      active={hovered}
      onHoverChange={setHovered}
      className="h-full rounded-xl"
    >
      <div className="border-border bg-card hover:border-foreground/25 relative flex h-full flex-col rounded-xl border p-4 transition-colors">
        <Link
          href={ROUTES.TABLE_DETAIL(table.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: table.name })}
        />
        <div className="pointer-events-none relative flex flex-1 items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
            <Table2 aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <p className="text-foreground truncate font-medium">{table.name}</p>
              {!table.can_edit && (
                <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
                  {t("readOnly")}
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground text-xs">
              {t("cardSize", { records: table.record_count, columns: table.column_count })}
            </p>
            {table.description && (
              <p className="text-muted-foreground mt-2 line-clamp-2 text-sm">{table.description}</p>
            )}
          </div>
        </div>
        <div className="text-muted-foreground pointer-events-none relative mt-3 flex items-center gap-2 border-t pt-3 text-xs">
          <span
            role="img"
            aria-label={t(`visibility.${table.visibility}`)}
            title={t(`visibility.${table.visibility}`)}
            className="pointer-events-auto"
          >
            <VisibilityIcon className="h-3.5 w-3.5" aria-hidden />
          </span>
          {t("editedWhen", { when: timeAgo(edited, tt, locale) })}
        </div>
      </div>
    </Beam>
  );
}
