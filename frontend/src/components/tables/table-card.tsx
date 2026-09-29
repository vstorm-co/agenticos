"use client";

import Link from "next/link";
import { useState } from "react";
import { Building2, Lock, Table2, Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { Beam } from "@/components/ui/beam";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";
import type { TableSummary } from "@/types/tables";

const VISIBILITY_ICON = { org: Building2, team: Users, private: Lock } as const;

/** One table in the catalog - the agents gallery's card, for a table. */
export function TableCard({ table }: { table: TableSummary }) {
  const t = useTranslations("pages.tables");
  const tc = useTranslations("common");
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
      className="rounded-xl"
    >
      <div className="border-border bg-card hover:border-foreground/25 relative rounded-xl border p-4 transition-colors">
        <Link
          href={ROUTES.TABLE_DETAIL(table.id)}
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: table.name })}
        />
        <div className="pointer-events-none relative flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
            <Table2 aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-foreground truncate font-medium">{table.name}</p>
            <p className="text-muted-foreground mt-1 line-clamp-2 min-h-[2.5rem] text-sm">
              {table.description || t("noDescription")}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="text-muted-foreground gap-1 font-normal">
                <VisibilityIcon className="h-3 w-3" aria-hidden />
                {t(`visibility.${table.visibility}`)}
              </Badge>
              <Badge variant="outline" className="text-muted-foreground font-normal">
                {t("schemaVersion", { version: table.schema_version })}
              </Badge>
              {!table.can_edit && (
                <Badge variant="outline" className="text-muted-foreground font-normal">
                  {t("readOnly")}
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="text-muted-foreground pointer-events-none relative mt-3 border-t pt-3 text-xs">
          {t("editedWhen", { when: formatDate(edited, locale) })}
        </div>
      </div>
    </Beam>
  );
}
