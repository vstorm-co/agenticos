"use client";

import { LayoutGrid } from "lucide-react";
import { useState, useId, useEffect } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useDashboardLayout } from "@/hooks/use-dashboard-layout";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { Button } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { sanitizeEntries, toStored, type StoredEntry } from "@/lib/dashboard/preference";
import type { WidgetDef } from "@/lib/dashboard/registry";

/** Copy an explicitly reviewed layout, without loading widgets or impersonating a member. */
export function OrganizationConsoleDashboard({
  value,
  catalog,
  disabled,
  onSave,
  onDirtyChange,
}: {
  value: { entries: StoredEntry[] } | null | undefined;
  catalog: WidgetDef[];
  disabled: boolean;
  onSave: (dashboard: { entries: StoredEntry[] } | null, onSaved: () => void) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience.dashboard");
  const dashboard = useTranslations("dashboard");
  const common = useTranslations("common");
  const mine = useDashboardLayout();
  const [draft, setDraft] = useState<{ entries: StoredEntry[] } | null | undefined>(undefined);
  const current = draft === undefined ? value : draft;
  const dirty = draft !== undefined;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useUnsavedChanges(id, { dirty, discard: () => setDraft(undefined) });
  const privateFilters = mine.storedEntries?.some(
    (entry) => entry.options?.agent_id || entry.options?.user_id,
  );
  return (
    <section className="space-y-3 border-t pt-4" aria-label={t("title")}>
      <h3 className="text-sm font-medium">{t("title")}</h3>
      <p className="text-muted-foreground text-xs leading-5">{t("hint")}</p>
      <Link
        href="/dashboard?view=org"
        className="text-primary text-sm underline underline-offset-4"
      >
        {t("arrange")}
      </Link>
      {mine.error ? (
        <ErrorState cta={{ label: common("retry"), onClick: mine.refetch }} />
      ) : mine.isLoading ? (
        <LoadingState variant="pending" />
      ) : (
        <>
          {privateFilters && <p className="text-muted-foreground text-xs">{t("privateFilters")}</p>}
          <div className="grid gap-2 sm:flex sm:flex-wrap max-sm:[&>button]:h-auto max-sm:[&>button]:min-h-11 max-sm:[&>button]:whitespace-normal">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || mine.storedEntries === null || !!privateFilters}
              onClick={() => {
                if (mine.storedEntries !== null)
                  setDraft({ entries: toStored(sanitizeEntries(mine.storedEntries)) });
              }}
            >
              {t("copy")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => setDraft(null)}
            >
              {t("inherit")}
            </Button>
          </div>
        </>
      )}
      {current === null || current === undefined ? (
        <p className="text-muted-foreground text-sm">{t("standard")}</p>
      ) : (
        <div className="bg-muted/30 rounded-lg border p-3">
          <p className="text-muted-foreground text-xs">{t("preview")}</p>
          <ul className="mt-2 space-y-2 text-sm">
            {current.entries.flatMap((entry, index) => {
              if (entry.kind === "section")
                return (
                  <li key={index} className="font-medium">
                    {entry.label}
                  </li>
                );
              const widget = catalog.find((item) => item.id === entry.widget);
              return widget ? (
                <li key={index} className="flex items-center gap-2">
                  <LayoutGrid className="text-muted-foreground size-4" aria-hidden />
                  {dashboard(`widgets.${widget.id}.title`)}
                </li>
              ) : (
                []
              );
            })}
          </ul>
          {current.entries.length === 0 && <p className="text-sm">{t("empty")}</p>}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:flex sm:justify-end max-sm:[&>button]:h-auto max-sm:[&>button]:min-h-11 max-sm:[&>button]:whitespace-normal">
        <Button
          type="button"
          variant="ghost"
          disabled={disabled || !dirty}
          onClick={() => setDraft(undefined)}
        >
          {t("discard")}
        </Button>
        <Button
          type="button"
          disabled={disabled || !dirty}
          onClick={() => {
            if (draft !== undefined) onSave(draft, () => setDraft(undefined));
          }}
        >
          {common("save")}
        </Button>
      </div>
    </section>
  );
}
