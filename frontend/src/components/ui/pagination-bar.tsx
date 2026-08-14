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
  const t = useTranslations("ui");
  const tc = useTranslations("common");
  if (total === 0) return null;

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = page * pageSize + 1;
  const end = Math.min(total, (page + 1) * pageSize);

  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground text-sm">
        {tc("rangeOfTotal", { start, end, total })}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPage(Math.max(0, page - 1))}
          disabled={page === 0 || isLoading}
          aria-label={t("previousPage")}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-muted-foreground px-2 text-sm">
          {page + 1} / {pageCount}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPage(Math.min(pageCount - 1, page + 1))}
          disabled={page >= pageCount - 1 || isLoading}
          aria-label={t("nextPage")}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
