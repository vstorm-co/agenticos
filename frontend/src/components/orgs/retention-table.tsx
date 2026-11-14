import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui";
import { RETENTION_CLASSES } from "@/lib/retention-api";

export const RETENTION_ROW =
  "block space-y-3 border-b px-4 py-4 last:border-0 @3xl/retention:table-row @3xl/retention:space-y-0 sm:px-5";
export const RETENTION_NAME =
  "block text-left text-sm font-medium @3xl/retention:table-cell @3xl/retention:w-2/5 @3xl/retention:px-5 @3xl/retention:py-4";
export const RETENTION_INPUT =
  "flex items-center justify-between gap-3 @3xl/retention:table-cell @3xl/retention:px-5 @3xl/retention:py-4";
export const RETENTION_EFFECTIVE =
  "text-muted-foreground block text-xs @3xl/retention:table-cell @3xl/retention:px-5 @3xl/retention:py-4";

/** Keep the same seven data classes and responsive columns during the policy read. */
export function RetentionTable({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.retention");
  return (
    <div className="@container/retention min-w-0 flex-1">
      <table className="w-full text-sm">
        <thead className="bg-muted/30 text-muted-foreground hidden @3xl/retention:table-header-group">
          <tr className="border-b">
            {["dataClass", "keepForDays", "whatSweeps"].map((key) => (
              <th key={key} scope="col" className="px-5 py-3 text-left text-xs font-medium">
                {t(key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="block @3xl/retention:table-row-group">{children}</tbody>
      </table>
    </div>
  );
}

export function RetentionFormLoading() {
  const t = useTranslations("pages.retention");
  const state = useTranslations("states");
  return (
    <div
      role="status"
      aria-label={state("loading")}
      aria-busy="true"
      className="flex flex-1 flex-col"
    >
      <RetentionTable>
        {RETENTION_CLASSES.map((name) => (
          <tr key={name} className={RETENTION_ROW}>
            <th scope="row" className={RETENTION_NAME}>
              {t(`classes.${name}`)}
            </th>
            <td className={RETENTION_INPUT}>
              <span className="text-muted-foreground text-xs @3xl/retention:hidden">
                {t("keepForDays")}
              </span>
              <Skeleton className="h-9 w-28 rounded-md" />
            </td>
            <td className={RETENTION_EFFECTIVE}>
              <Skeleton className="h-4 w-44 max-w-full" />
            </td>
          </tr>
        ))}
      </RetentionTable>
      <div className="space-y-3 border-t p-4 sm:p-5" aria-hidden="true">
        <Skeleton className="h-10 w-20 rounded-md" />
        <p className="text-muted-foreground text-xs">{t("hardDeleteNotice")}</p>
      </div>
    </div>
  );
}
