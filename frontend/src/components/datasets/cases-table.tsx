"use client";

import {
  CheckCheck,
  FileQuestion,
  Hash,
  ListChecks,
  MoreHorizontal,
  PanelRightOpen,
  Pencil,
  Tags,
  Trash2,
  Wrench,
} from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DataTable,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  type Column,
} from "@/components/ui";
import type { DatasetCase } from "@/types/datasets";
import { CaseSourceChip, CaseTag, DatasetChip } from "./dataset-chip";

export function CasesTable({
  cases,
  onOpen,
  onRemove,
  offset = 0,
  activeCaseId,
  loading = false,
}: {
  cases: DatasetCase[];
  loading?: boolean;
  onOpen: (item: DatasetCase) => void;
  onRemove?: (item: DatasetCase) => void;
  offset?: number;
  activeCaseId?: string;
}) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const positions = new Map(cases.map((item, index) => [item.id, offset + index + 1]));
  const question = (item: DatasetCase) =>
    item.masked ? t("maskedConversation") : item.anonymised_at ? t("anonymisedInput") : item.input;
  const columns: Column<DatasetCase>[] = [
    {
      key: "number",
      header: (
        <>
          <Hash className="size-3.5" aria-hidden />
          <span className="sr-only">{t("table.number")}</span>
        </>
      ),
      className: "w-12 text-muted-foreground tabular-nums",
      hideBelow: "sm",
      cell: (item) => positions.get(item.id),
    },
    {
      key: "input",
      header: (
        <span className="inline-flex items-center gap-2">
          <FileQuestion className="size-3.5" aria-hidden />
          {t("table.question")}
        </span>
      ),
      className: "min-w-0 md:w-[34%]",
      cell: (item) => (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen(item);
          }}
          className="focus-visible:ring-ring group w-full min-w-0 rounded-sm text-left outline-none focus-visible:ring-2"
        >
          <span className="line-clamp-2 text-sm font-medium break-words">{question(item)}</span>
          <span className="mt-1.5 flex flex-wrap gap-1 md:hidden">
            {!item.masked && <CaseSourceChip source={item.source} />}
          </span>
        </button>
      ),
    },
    {
      key: "expectations",
      header: (
        <span className="inline-flex items-center gap-2">
          <CheckCheck className="size-3.5" aria-hidden />
          {t("table.expectations")}
        </span>
      ),
      hideBelow: "md",
      className: "min-w-0 md:w-[36%]",
      cell: (item) =>
        item.masked ? (
          <span className="text-muted-foreground text-xs">{t("maskedConversation")}</span>
        ) : (
          <div className="max-w-md space-y-1.5">
            <div className="flex flex-wrap gap-1">
              {item.reference_answer !== null && (
                <DatasetChip tone="green" icon={CheckCheck}>
                  {t("field.reference_answer")}
                </DatasetChip>
              )}
              {item.counter_example !== null && (
                <DatasetChip tone="red">{t("field.counter_example")}</DatasetChip>
              )}
              {item.checks.length > 0 && (
                <DatasetChip tone="blue" icon={ListChecks}>
                  {t("checkCount", { count: item.checks.length })}
                </DatasetChip>
              )}
              {item.expected_tool_calls.length > 0 && (
                <DatasetChip tone="purple" icon={Wrench}>
                  {t("expectedCalls", { count: item.expected_tool_calls.length })}
                </DatasetChip>
              )}
            </div>
            <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed break-words">
              {item.reference_answer ??
                item.counter_example ??
                (item.checks.length + item.expected_tool_calls.length === 0 ? "—" : null)}
            </p>
          </div>
        ),
    },
    {
      key: "source",
      header: t("table.source"),
      hideBelow: "lg",
      className: "w-32",
      cell: (item) => <CaseSourceChip source={item.source} />,
    },
    {
      key: "tags",
      header: (
        <span className="inline-flex items-center gap-2">
          <Tags className="size-3.5" aria-hidden />
          {t("table.tags")}
        </span>
      ),
      hideBelow: "lg",
      className: "w-28",
      cell: (item) => (
        <div className="flex max-w-48 flex-wrap gap-1">
          {item.masked || item.tags.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            item.tags.map((tag) => <CaseTag key={tag} tag={tag} />)
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("table.actions")}</span>,
      align: "right",
      className: "w-20",
      cell: (item) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground size-7"
            aria-label={t("openCase")}
            onClick={(event) => {
              event.stopPropagation();
              onOpen(item);
            }}
          >
            <PanelRightOpen className="size-3.5" aria-hidden />
          </Button>
          {onRemove && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground size-7"
                  aria-label={t("caseActions")}
                  onClick={(event) => event.stopPropagation()}
                >
                  <MoreHorizontal className="size-3.5" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(event) => event.stopPropagation()}>
                <DropdownMenuItem onSelect={() => onOpen(item)}>
                  <Pencil className="size-4" aria-hidden />
                  {t("edit")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive-ink focus:text-destructive-ink"
                  onSelect={() => onRemove(item)}
                >
                  <Trash2 className="size-4" aria-hidden />
                  {tc("delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      ),
    },
  ];
  return (
    <DataTable
      className="[&_thead]:bg-foreground/[0.025] [&_th]:text-muted-foreground [&_tbody_tr]:border-border/50 [&_td]:border-border/40 rounded-none border-0 bg-transparent [&_td]:border-r [&_td:last-child]:border-r-0 [&_th]:text-xs [&_th]:font-medium"
      columns={columns}
      rows={cases}
      loading={loading}
      getRowKey={(item) => item.id}
      onRowClick={onOpen}
      isRowActive={(item) => item.case_id === activeCaseId}
    />
  );
}
