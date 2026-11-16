"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/**
 * The pager for a list the server pages — the counterpart of `Pager` in
 * `list-controls.tsx`, which pages a list the client already holds.
 *
 * One control instead of the three dialects the admin pages grew (#284):
 * a "showing X–Y of N" range, chevron buttons, nothing when there is nothing.
 * The page-size select stays in the caller's toolbar — which sizes a page
 * offers is the page's decision, which page is shown is this control's.
 */
export function PaginationBar({
  page,
  pageSize,
  total,
  isLoading,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  isLoading?: boolean;
  onPage: (page: number) => void;
}) {
  const tc = useTranslations("common");
  if (total === 0) return null;

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = page * pageSize + 1;
  const end = Math.min(total, (page + 1) * pageSize);

  return (
    <div className="flex min-h-9 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <span className="text-muted-foreground text-[13px] tabular-nums">
        {tc("rangeOfTotal", { start, end, total })}
      </span>
      <PageNavigation
        page={page}
        pageCount={pageCount}
        hasNext={page < pageCount - 1}
        isLoading={isLoading}
        onPage={onPage}
      />
    </div>
  );
}

/** Shared navigation for counted pages and cursor-backed lists. */
export function PageNavigation({
  page,
  pageCount,
  hasNext,
  isLoading = false,
  onPage,
}: {
  page: number;
  pageCount?: number;
  hasNext: boolean;
  isLoading?: boolean;
  onPage: (page: number) => void;
}) {
  const t = useTranslations("ui");
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="size-8 p-0"
        disabled={page <= 0 || isLoading}
        onClick={() => onPage(page - 1)}
        aria-label={t("previousPage")}
      >
        <ChevronLeft className="size-4" aria-hidden />
      </Button>
      {pageCount !== undefined && (
        <span
          className="text-foreground/80 min-w-12 px-2 text-center text-[13px] font-medium tabular-nums"
          aria-live="polite"
          aria-atomic="true"
        >
          {page + 1} / {pageCount}
        </span>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="size-8 p-0"
        disabled={!hasNext || isLoading}
        onClick={() => onPage(page + 1)}
        aria-label={t("nextPage")}
      >
        <ChevronRight className="size-4" aria-hidden />
      </Button>
    </div>
  );
}
