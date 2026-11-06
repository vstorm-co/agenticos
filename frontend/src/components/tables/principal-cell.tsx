"use client";

import { useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Input, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import {
  useTablePrincipals,
  useTableAssignees,
  type PrincipalOption,
} from "@/hooks/use-table-principals";
import { RecordSourceBadge } from "./record-source-badge";
import type { CellValue, RecordSource } from "@/types/tables";

function idsOf(value: CellValue): string[] {
  return Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
}

function Chosen({
  ids,
  items,
  kind,
}: {
  ids: string[];
  items: RecordSource[];
  kind: "user" | "agent";
}) {
  const t = useTranslations("tables.principals");
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1.5">
      {ids.map((id) => (
        <RecordSourceBadge
          key={id}
          source={items.find((item) => item.id === id) ?? { kind, id, name: t("unavailable") }}
        />
      ))}
    </span>
  );
}

export function PrincipalBadges({ value, kind }: { value: CellValue; kind: "user" | "agent" }) {
  const { items } = useTablePrincipals(kind);
  return <Chosen ids={idsOf(value)} items={items} kind={kind} />;
}

interface PrincipalCellProps {
  id: string;
  label: string;
  value: CellValue;
  kind: "user" | "agent";
  multiple: boolean;
  onChange: (value: CellValue) => void;
  disabled?: boolean;
  tableId?: string;
}

/** Only managed-task assignment narrows the ordinary identity directory. */
export function PrincipalCell(props: PrincipalCellProps) {
  return props.tableId && props.kind === "user" ? (
    <ScopedPrincipalCell {...props} tableId={props.tableId} />
  ) : (
    <PrincipalInput {...props} />
  );
}

function ScopedPrincipalCell(props: PrincipalCellProps & { tableId: string }) {
  const query = useTableAssignees(props.tableId);
  return (
    <PrincipalInput
      {...props}
      options={
        query.data === null
          ? undefined
          : { items: query.data ?? [], isLoading: query.isPending, error: query.error }
      }
    />
  );
}

function PrincipalInput({
  id,
  label,
  value,
  kind,
  multiple,
  onChange,
  disabled,
  options,
}: PrincipalCellProps & {
  options?: { items: PrincipalOption[]; isLoading: boolean; error: Error | null };
}) {
  const t = useTranslations("tables.principals");
  const [open, setOpen] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const searchField = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const directory = useTablePrincipals(kind, options === undefined);
  const { items, isLoading, error } = options ?? directory;
  const selected = idsOf(value);
  const atLimit = multiple && selected.length >= 100;
  const matches = items
    .filter((item) => !item.archived || selected.includes(item.id ?? ""))
    .filter((item) =>
      `${item.name} ${item.detail ?? ""}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
    )
    .slice(0, 50);
  const choose = (item: RecordSource) => {
    if (!item.id || (atLimit && !selected.includes(item.id))) return;
    onChange(
      multiple
        ? selected.includes(item.id)
          ? selected.filter((id) => id !== item.id)
          : [...selected, item.id]
        : item.id,
    );
    if (!multiple) setOpen(false);
  };
  return (
    <Popover
      modal
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          role="combobox"
          aria-expanded={open}
          aria-label={label}
          className="h-auto min-h-9 w-full justify-between py-2 text-left font-normal"
        >
          {selected.length ? (
            <Chosen ids={selected} items={items} kind={kind} />
          ) : (
            <span className="text-muted-foreground">
              {t(kind === "user" ? "choosePeople" : "chooseAgents")}
            </span>
          )}
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="flex max-h-[min(24rem,var(--radix-popover-content-available-height))] w-80 flex-col gap-2 overflow-hidden p-2"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchField.current?.focus();
        }}
      >
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label={t("search")}
          placeholder={t("search")}
          ref={searchField}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              list.current?.querySelector<HTMLButtonElement>("button")?.focus();
            }
          }}
        />
        {isLoading ? (
          <p className="text-muted-foreground p-2 text-sm" role="status">
            {t("loading")}
          </p>
        ) : error ? (
          <p className="text-destructive p-2 text-sm" role="alert">
            {t("loadError")}
          </p>
        ) : (
          <div
            ref={list}
            onKeyDown={(event) => {
              if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
              const buttons = Array.from(
                list.current?.querySelectorAll<HTMLButtonElement>("button") ?? [],
              );
              const index = buttons.findIndex((button) => button === event.target);
              if (index < 0) return;
              event.preventDefault();
              buttons[
                (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length
              ]?.focus();
            }}
            role="listbox"
            tabIndex={-1}
            aria-label={label}
            aria-multiselectable={multiple}
            className="max-h-64 min-h-0 touch-pan-y overflow-y-auto overscroll-contain"
          >
            {matches.map((item) => (
              <button
                key={item.id}
                role="option"
                disabled={atLimit && !selected.includes(item.id ?? "")}
                aria-selected={selected.includes(item.id ?? "")}
                type="button"
                onClick={() => choose(item)}
                className="hover:bg-accent flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left disabled:opacity-50"
              >
                <span className="min-w-0">
                  <RecordSourceBadge source={item} />
                  {item.detail && (
                    <span className="text-muted-foreground ml-8 block truncate text-xs">
                      {item.detail}
                    </span>
                  )}
                </span>
                {selected.includes(item.id ?? "") && (
                  <Check className="size-4 shrink-0" aria-hidden />
                )}
              </button>
            ))}
            {!matches.length && <p className="text-muted-foreground p-2 text-sm">{t("empty")}</p>}
          </div>
        )}
        {!!selected.length && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full"
            onClick={() => onChange(null)}
          >
            {t("clear")}
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
