"use client";

import { useTranslations } from "next-intl";

import type { FieldRow } from "@/lib/openapi/reference";

/** Parameters or body fields: name, where it goes, its type and what it means. */
export function FieldTable({ rows, showLocation }: { rows: FieldRow[]; showLocation: boolean }) {
  const t = useTranslations("apiReference");
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[32rem] text-left text-xs">
        <thead className="text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 pr-3 font-medium">{t("name")}</th>
            {showLocation && <th className="py-1.5 pr-3 font-medium">{t("location")}</th>}
            <th className="py-1.5 pr-3 font-medium">{t("type")}</th>
            <th className="py-1.5 font-medium">{t("fieldDescription")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.location ?? "body"}-${row.name}`} className="border-b last:border-0">
              <td className="py-1.5 pr-3 align-top font-mono whitespace-nowrap">
                {row.name}
                {row.required && <span className="text-destructive ml-1">{t("requiredMark")}</span>}
              </td>
              {showLocation && (
                <td className="text-muted-foreground py-1.5 pr-3 align-top">{row.location}</td>
              )}
              <td className="py-1.5 pr-3 align-top font-mono whitespace-nowrap">{row.type}</td>
              <td className="text-muted-foreground py-1.5 align-top">{row.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
