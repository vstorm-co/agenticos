"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";
import { keyRows, type CheckDraft, type KeyRow } from "./case-form";

/** A keys check's facts: what each one is and the value the answer must carry. */
export function KeysValue({
  check,
  number,
  disabled,
  onChange,
}: {
  check: CheckDraft;
  number: number;
  disabled: boolean;
  onChange: (patch: Partial<CheckDraft>) => void;
}) {
  const t = useTranslations("datasets.keysCheck");
  const rows = keyRows(check);
  const set = (keys: KeyRow[]) => onChange({ rest: { ...check.rest, keys } });
  const edit = (at: number, patch: Partial<KeyRow>) =>
    set(rows.map((row, index) => (index === at ? { ...row, ...patch } : row)));
  return (
    <div className="min-w-0 flex-1 space-y-2">
      {rows.map((row, at) => (
        <div key={at} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-2">
          <Input
            disabled={disabled}
            value={row.key}
            aria-label={t("key", { number, row: at + 1 })}
            placeholder={t("keyPlaceholder")}
            onChange={(event) => edit(at, { key: event.target.value })}
          />
          <Input
            disabled={disabled}
            value={row.value}
            aria-label={t("value", { number, row: at + 1 })}
            placeholder={t("valuePlaceholder")}
            onChange={(event) => edit(at, { value: event.target.value })}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            aria-label={t("remove", { number, row: at + 1 })}
            onClick={() => set(rows.filter((_, index) => index !== at))}
          >
            <X className="size-4" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => set([...rows, { key: "", value: "" }])}
      >
        <Plus className="size-4" />
        {t("add")}
      </Button>
    </div>
  );
}
