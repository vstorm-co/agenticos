"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";

/**
 * The pager for a table's records: `skip`/`limit` driven by `page`, `has_more`
 * deciding whether "next" is enabled - there is no `total` (counting a
 * filtered table is not cheap), so `PaginationBar`'s page-count display does
 * not fit here.
 */
export function HasMorePager({
  page,
  hasMore,
  isLoading,
  onPage,
}: {
  page: number;
  hasMore: boolean;
  isLoading?: boolean;
  onPage: (page: number) => void;
}) {
  const t = useTranslations("ui");
  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPage(Math.max(0, page - 1))}
        disabled={page === 0 || isLoading}
        aria-label={t("previousPage")}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPage(page + 1)}
        disabled={!hasMore || isLoading}
        aria-label={t("nextPage")}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
