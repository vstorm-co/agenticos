"use client";

import { PageNavigation } from "@/components/ui/pagination-bar";

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
  return (
    <div className="flex min-h-9 items-center justify-end">
      <PageNavigation page={page} hasNext={hasMore} isLoading={isLoading} onPage={onPage} />
    </div>
  );
}
