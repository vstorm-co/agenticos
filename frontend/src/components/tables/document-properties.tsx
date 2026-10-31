"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { RecordSourceBadge } from "./record-source-badge";
import { Button, Input } from "@/components/ui";
import { formatDateTime } from "@/lib/utils";
import {
  documentProperties,
  SYSTEM_DOCUMENT_PROPERTIES,
  withDocumentProperty,
} from "@/lib/document-properties";
import type { RecordRead } from "@/types/tables";

export type DocumentMetadata = Pick<
  RecordRead,
  "created_at" | "updated_at" | "created_by" | "updated_by" | "created_source" | "updated_source"
>;

/** System properties come from the record, never from editable Markdown. */
export function DocumentProperties({
  id,
  value,
  onChange,
  disabled,
  metadata,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  metadata?: DocumentMetadata;
}) {
  const t = useTranslations("tables.markdown");
  const locale = useLocale();
  const [key, setKey] = useState("");
  const [text, setText] = useState("");
  const properties = documentProperties(value);
  const keyTaken =
    SYSTEM_DOCUMENT_PROPERTIES.has(key.trim()) || properties.document.has(key.trim());
  const dates = [
    ["createdAt", metadata?.created_at],
    ["updatedAt", metadata?.updated_at ?? metadata?.created_at],
  ] as const;
  return (
    <div className="shrink-0 space-y-3 border-b p-4">
      <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
        {dates.map(([label, date]) => (
          <div
            key={label}
            className="flex flex-wrap items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1"
          >
            <dt className="text-muted-foreground">{t(label)}</dt>
            <dd>{date ? formatDateTime(date, locale) : t("onCreation")}</dd>
          </div>
        ))}
        <div className="flex min-w-0 items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1">
          <dt className="text-muted-foreground shrink-0">{t("createdBy")}</dt>
          <dd className="truncate" title={metadata?.created_by ?? undefined}>
            <RecordSourceBadge
              source={metadata?.created_source}
              principalId={metadata?.created_by}
              fallback={t("automatic")}
            />
          </dd>
        </div>
        <div className="flex min-w-0 items-baseline justify-between gap-2 sm:flex-col sm:items-start sm:gap-1">
          <dt className="text-muted-foreground shrink-0">{t("updatedBy")}</dt>
          <dd className="max-w-full min-w-0">
            <RecordSourceBadge
              source={metadata?.updated_source ?? metadata?.created_source}
              principalId={metadata?.updated_by ?? metadata?.created_by}
              fallback={t("automatic")}
            />
          </dd>
        </div>
      </dl>
      <details>
        <summary className="text-muted-foreground cursor-pointer text-xs">
          {t("properties")}
        </summary>
        <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
          {!properties.valid && (
            <p role="status" className="text-muted-foreground text-xs">
              {t("legacyProperties")}
            </p>
          )}
          {properties.fields.map((field) => (
            <div key={field.key} className="flex items-center gap-2">
              <label
                className="w-28 shrink-0 truncate text-xs"
                htmlFor={`${id}-property-${field.key}`}
              >
                {field.key}
              </label>
              <Input
                id={`${id}-property-${field.key}`}
                aria-label={field.key}
                value={field.editable ? field.value : field.value || t("complexProperty")}
                disabled={disabled || !field.editable}
                onChange={(event) =>
                  onChange(withDocumentProperty(value, field.key, event.target.value))
                }
              />
              {!disabled && field.editable && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("removeProperty", { name: field.key })}
                  onClick={() => onChange(withDocumentProperty(value, field.key, null))}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
          ))}
          {!disabled && properties.valid && properties.fields.length < 32 && (
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
              <Input
                className="col-span-2 min-w-0 sm:col-span-1"
                aria-label={t("propertyName")}
                placeholder={t("propertyName")}
                value={key}
                maxLength={64}
                onChange={(event) => setKey(event.target.value)}
              />
              <Input
                className="min-w-0 flex-1"
                aria-label={t("propertyValue")}
                placeholder={t("propertyValue")}
                value={text}
                maxLength={1000}
                onChange={(event) => setText(event.target.value)}
              />
              <Button
                type="button"
                size="icon"
                variant="outline"
                aria-label={t("addProperty")}
                disabled={!key.trim() || keyTaken}
                onClick={() => {
                  onChange(withDocumentProperty(value, key.trim(), text));
                  setKey("");
                  setText("");
                }}
              >
                <Plus className="size-4" />
              </Button>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
