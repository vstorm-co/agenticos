"use client";

import Link from "next/link";
import { Check, FileText, Plus } from "lucide-react";

import { Badge, Pager, SearchInput, useListControls } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { ContextFileSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ContextGalleryProps {
  files: ContextFileSummary[];
  /** How many the organization has, which may exceed what was fetched. */
  total: number;
  /** `spec.context_ids`. */
  selectedIds: string[];
  onToggle: (fileId: string) => void;
  disabled?: boolean;
}

/**
 * Every context file the organization has, as a gallery to pick from.
 *
 * A gallery rather than a checkbox list for the same reason skills use one: a
 * file is chosen on what its description says, and the mode badge tells the
 * author whether picking it spends tokens on every run or only when the model
 * reaches for it. Files that no longer exist are named rather than dropped, so
 * the Builder shows an orphan rather than letting it vanish silently.
 */
export function ContextGallery({
  files,
  total,
  selectedIds,
  onToggle,
  disabled,
}: ContextGalleryProps) {
  const t = useTranslations("agents");
  const tContext = useTranslations("context");
  const chosen = new Set(selectedIds);
  const known = new Set(files.map((file) => file.id));
  const orphaned = files.length >= total ? selectedIds.filter((id) => !known.has(id)) : [];

  const list = useListControls({
    items: files,
    matches: (file, query) =>
      file.name.toLowerCase().includes(query) ||
      (file.description ?? "").toLowerCase().includes(query),
  });

  if (files.length === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <FileText className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-muted-foreground mt-2 text-sm">{t("organizationHasNoContext")}</p>
        <Link
          href={ROUTES.CONTEXT}
          className="mt-3 inline-flex items-center gap-1.5 text-sm underline underline-offset-4"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("addOne")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {files.length > 8 && (
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchContext")} />
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        {list.visible.map((file) => {
          const isOn = chosen.has(file.id);
          return (
            <button
              key={file.id}
              type="button"
              role="checkbox"
              aria-checked={isOn}
              aria-label={file.name}
              disabled={disabled}
              onClick={() => onToggle(file.id)}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-4 text-left transition-colors",
                isOn ? "border-brand bg-brand/5" : "hover:border-foreground/20",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                  isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
                )}
              >
                {isOn && <Check className="h-3 w-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{file.name}</span>
                  <Badge variant={file.mode === "inject" ? "secondary" : "outline"}>
                    {tContext(file.mode === "inject" ? "modeInject" : "modeLink")}
                  </Badge>
                  {!file.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
                </span>
                {file.description !== null && (
                  <span className="text-muted-foreground mt-1 block text-sm">
                    {file.description}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        counted={t("contextCount", { count: list.total })}
      />

      {orphaned.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("orphanedContext", { count: orphaned.length })}{" "}
          <span className="font-mono break-all">{orphaned.join(", ")}</span>
        </p>
      )}

      <p className="text-muted-foreground text-xs">
        {t.rich("contextLoadingHint", {
          link: (chunks) => (
            <Link href={ROUTES.CONTEXT} className="underline underline-offset-4">
              {chunks}
            </Link>
          ),
        })}
      </p>
    </div>
  );
}
