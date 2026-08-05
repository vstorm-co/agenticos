"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/** What a page holds before somebody has to ask for the next one. */
export const PAGE_SIZE = 50;

/**
 * Search, filter and paging over a list the client already holds.
 *
 * For a list the client *does not* hold - one that grows with an organization's
 * content - the server pages it and the query is a request, not a filter. This
 * is for the other kind: a catalog compiled into the deployment, or a set small
 * enough that a round trip per keystroke would be the slower design.
 *
 * Returns the visible slice plus what a pager needs to describe it. Resetting to
 * the first page when the query changes is the part that is easy to forget and
 * looks broken when it is missing: filtering to three results while sitting on
 * page four shows an empty list under a control that says there are three.
 */
export function useListControls<T>({
  items,
  matches,
  pageSize = PAGE_SIZE,
}: {
  items: T[];
  /** Whether one item survives the query. Case folding is the caller's. */
  matches: (item: T, query: string) => boolean;
  pageSize?: number;
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? items.filter((item) => matches(item, needle)) : items;
    // `matches` is left out on purpose: it is a fresh closure on every render
    // for most callers, and depending on it would recompute constantly for no
    // gain, since the data it reads is `items` and `query`.
  }, [items, query]);

  // Clamped rather than reset in an effect: an effect would render one frame of
  // the empty page first, which is the flicker this avoids.
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pageCount - 1);
  const visible = filtered.slice(current * pageSize, current * pageSize + pageSize);

  return {
    query,
    setQuery: (next: string) => {
      setQuery(next);
      setPage(0);
    },
    visible,
    total: items.length,
    matched: filtered.length,
    page: current,
    pageCount,
    setPage,
  };
}

/** The search box, sized for a toolbar rather than a form. */
export function SearchInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <div className={cn("relative w-full sm:w-64", className)}>
      <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="pl-9"
      />
    </div>
  );
}

/**
 * The pager, which renders nothing when there is only one page.
 *
 * A control that cannot do anything is a control somebody reaches for anyway -
 * and on the common case, a catalog that fits on one page, it would be the only
 * thing at the foot of the list.
 */
export function Pager({
  page,
  pageCount,
  matched,
  total,
  onPage,
  noun,
}: {
  page: number;
  pageCount: number;
  matched: number;
  total: number;
  onPage: (page: number) => void;
  /** Plural, for the count line: "servers", "skills". */
  noun: string;
}) {
  const t = useTranslations("ui");
  if (pageCount <= 1) {
    return matched === total ? null : (
      <p className="text-muted-foreground text-xs">
        {matched} of {total} {noun}
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-muted-foreground text-xs">
        {matched === total ? `${total} ${noun}` : `${matched} of ${total} ${noun}`} · page{" "}
        {page + 1} of {pageCount}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={page === 0}
          onClick={() => onPage(page - 1)}
          aria-label={t("previousPage")}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pageCount - 1}
          onClick={() => onPage(page + 1)}
          aria-label={t("nextPage")}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

/**
 * A value that stops changing while somebody is still typing.
 *
 * For the other kind of list - one the server pages, where the query is a
 * request rather than a filter. Without this, a search box issues a round trip
 * per keystroke and the answers can land out of order.
 */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);

  return settled;
}
