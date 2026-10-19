"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/** What a page holds before somebody has to ask for the next one. */
export const PAGE_SIZE = 50;

/** What a page of a picker holds: cards with a description each, in a side panel. */
export const PICKER_PAGE_SIZE = 10;

/**
 * A picker's items with the ones already chosen first, in their own order.
 *
 * The choice is read once, when the picker opens: a card that jumped to the top
 * the moment it was ticked would move out from under the pointer, and the next
 * click would land on its neighbour.
 */
export function useChosenFirst<T extends { id: string }>(items: T[], selectedIds: string[]): T[] {
  const [chosen] = useState(() => new Set(selectedIds));
  return useMemo(
    () => [
      ...items.filter((item) => chosen.has(item.id)),
      ...items.filter((item) => !chosen.has(item.id)),
    ],
    [items, chosen],
  );
}

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
  query: controlled,
  onQueryChange,
}: {
  items: T[];
  /** Whether one item survives the query. Case folding is the caller's. */
  matches: (item: T, query: string) => boolean;
  pageSize?: number;
  /**
   * The query, where the caller owns it. Omit and this holds its own.
   *
   * Controlled for one reason: a caller whose `items` *depend* on the query -
   * because part of the list comes from the server and part is in hand - cannot
   * read the query out of the hook it has to build the items for. The MCP list
   * is that case: a hundred catalog servers filtered locally, plus whatever the
   * public registry answers for the same words.
   */
  query?: string;
  onQueryChange?: (next: string) => void;
}) {
  const [own, setOwn] = useState("");
  const query = controlled ?? own;
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
      if (onQueryChange) onQueryChange(next);
      else setOwn(next);
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
  label,
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
  /** What the box searches, for a screen reader, where the placeholder is a
   *  single word the column it sits in leaves room for. Defaults to it. */
  label?: string;
  /** For a caller that opened this box *in order to* search - the chat's
   *  collapsed rail. Off everywhere else: a box that grabs the cursor on every
   *  page load takes it from whatever somebody was typing in. */
  autoFocus?: boolean;
}) {
  return (
    <div className={cn("relative w-full sm:w-64", className)}>
      <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2" />
      {/* The height of the filters beside it; still 16px on a phone, where iOS
          zooms into anything smaller. */}
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label ?? placeholder}
        autoFocus={autoFocus}
        className="border-foreground/12 h-8 rounded-lg border pl-8 md:text-[13px]"
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
  counted,
}: {
  page: number;
  pageCount: number;
  matched: number;
  total: number;
  onPage: (page: number) => void;
  /**
   * `total`, already counted through an ICU plural: "40 skills", "1 server".
   *
   * A word rather than a phrase was what this used to take - `noun="skills"`,
   * six call sites, six English words - and `{matched} of {total} {noun}`
   * rendered `3 of 40 skills` under `pl`. English is the only language where a
   * noun beside a number needs no agreement; Polish declines it three ways, so
   * the noun has to sit *inside* the plural and no parameter can carry it.
   *
   * Formatted by the caller because the noun belongs to the caller's namespace:
   * `mcp.serverCount`, `pages.skills.skillCount`. `ui` would otherwise collect a
   * count message for every list in the product (#362).
   */
  counted: string;
}) {
  const t = useTranslations("ui");
  if (pageCount <= 1) {
    return matched === total ? null : (
      <p className="text-muted-foreground text-xs">{t("matchedOfTotal", { matched, counted })}</p>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-muted-foreground text-xs">
        {matched === total
          ? t("pagerAll", { counted, page: page + 1, pageCount })
          : t("pagerMatched", { matched, counted, page: page + 1, pageCount })}
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
