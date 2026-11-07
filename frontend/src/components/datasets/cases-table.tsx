"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button, DataTable, type Column } from "@/components/ui";
import type { DatasetCase } from "@/types/datasets";

/** The same readable table used by the console's other resource workspaces. */
export function CasesTable({
  cases,
  onOpen,
  onRemove,
}: {
  cases: DatasetCase[];
  onOpen: (item: DatasetCase) => void;
  onRemove?: (item: DatasetCase) => void;
}) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const question = (item: DatasetCase) =>
    item.masked ? t("maskedConversation") : item.anonymised_at ? t("anonymisedInput") : item.input;
  const columns: Column<DatasetCase>[] = [
    {
      key: "input",
      header: t("table.question"),
      className: "min-w-0 md:w-[48%]",
      cell: (item) => (
        <button
          type="button"
          onClick={() => onOpen(item)}
          className="focus-visible:ring-ring w-full min-w-0 rounded-sm text-left outline-none focus-visible:ring-2"
        >
          <span className="line-clamp-2 text-sm font-medium break-words">{question(item)}</span>
          <span className="text-muted-foreground mt-1 block text-xs">
            {item.source !== "manual" && t(`source.${item.source}`)}
            {item.checks.length > 0 && (
              <>
                {item.source !== "manual" && " · "}
                {t("checkCount", { count: item.checks.length })}
              </>
            )}
          </span>
        </button>
      ),
    },
    {
      key: "expectations",
      header: t("table.expectations"),
      hideBelow: "md",
      cell: (item) => (
        <span className="text-muted-foreground line-clamp-2 max-w-sm text-sm break-words">
          {item.masked
            ? t("maskedConversation")
            : (item.reference_answer ??
              item.counter_example ??
              t("checkCount", { count: item.checks.length + item.expected_tool_calls.length }))}
        </span>
      ),
    },
    {
      key: "tags",
      header: t("table.tags"),
      hideBelow: "lg",
      cell: (item) => (
        <div
          className="flex max-w-52 flex-wrap gap-1"
          title={item.masked ? undefined : item.tags.join(", ")}
        >
          {item.masked || item.tags.length === 0 ? (
            "—"
          ) : (
            <>
              {item.tags.map((tag) => (
                <Badge key={tag} variant="outline" className="max-w-40 truncate font-normal">
                  {tag}
                </Badge>
              ))}
            </>
          )}
        </div>
      ),
    },
  ];
  if (onRemove) {
    columns.push({
      key: "actions",
      header: <span className="sr-only">{t("table.actions")}</span>,
      align: "right",
      className: "w-12",
      cell: (item) => (
        <Button
          variant="ghost"
          size="icon"
          aria-label={tc("delete")}
          onClick={() => onRemove(item)}
        >
          <Trash2 className="size-4" />
        </Button>
      ),
    });
  }
  return (
    <DataTable
      className="rounded-none border-0"
      columns={columns}
      rows={cases}
      getRowKey={(item) => item.id}
    />
  );
}
