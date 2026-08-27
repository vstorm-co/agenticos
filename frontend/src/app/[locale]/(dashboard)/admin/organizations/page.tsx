"use client";

import { useEffect, useMemo, useState } from "react";

import { ErrorState } from "@/components/states";
import {
  Badge,
  DataTable,
  ListCard,
  ListCardFootRow,
  PaginationBar,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import { ADMIN_ORG_SORT_KEYS, useAdminOrganizations, useUrlSort } from "@/hooks";
import type { AdminOrgKind } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { formatDate } from "@/lib/utils";
import { useLocale, useTranslations } from "next-intl";

import type { AdminOrganization } from "@/types/admin";

/** One server page - the same fixed size every other paged list uses. */
const PAGE_SIZE = 50;

/** The kinds, as catalog keys: a module constant has no translator to reach. */
const KINDS: { value: AdminOrgKind; labelKey: string }[] = [
  { value: "all", labelKey: "kindAll" },
  { value: "personal", labelKey: "kindPersonal" },
  { value: "team", labelKey: "kindTeam" },
];

/**
 * Every tenant on the deployment, one row each - its own tab rather than a
 * table at the bottom of the overview, where it competed with the figures for
 * a reader who came for exactly one of the two.
 *
 * Search, sort, filter and paging are the server's, applied in SQL before
 * `OFFSET`/`LIMIT`. The page carried none of them until the route could answer
 * one (#921): it asked for fifty rows in one fixed order and said nothing about
 * the rest, so a deployment admin could find one person among hundreds - the
 * sibling tab has had all four since #284 - and could not find one tenant among
 * fifty. Sorting the page after it arrives is the thing that is *not* done
 * here, because a client sort claims a whole-collection order fifty rows cannot
 * deliver.
 */
export default function AdminOrganizationsPage() {
  const t = useTranslations("pages.admin");
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<AdminOrgKind>("all");
  const [page, setPage] = useState(0);
  const { sort, setSort } = useUrlSort(ADMIN_ORG_SORT_KEYS, { by: "created_at", dir: "desc" });
  // Typing is not a request per keystroke. The delay is on the term the query
  // key is built from rather than on the input, so the field itself stays live
  // - the same 300ms the users tab beside it waits.
  const [term, setTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Back to the first page whenever the narrowing moves - page 3 of a different
  // list is a list somebody has to page back out of.
  if (useChanged(`${term}|${kind}|${sort.by}|${sort.dir}`)) {
    setPage(0);
  }

  const { organizations, total, isLoading, error } = useAdminOrganizations({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    search: term || undefined,
    sortBy: sort.by,
    sortDir: sort.dir,
    kind,
  });

  const columns = useMemo<Column<AdminOrganization>[]>(
    () => [
      {
        key: "name",
        header: t("name"),
        className: "pl-5",
        sortable: true,
        cell: (org) => (
          <>
            <span className="text-foreground font-medium">{org.name}</span>
            {org.is_personal && (
              <Badge variant="outline" className="ml-2 text-[10px]">
                {t("personal")}
              </Badge>
            )}
          </>
        ),
      },
      {
        key: "slug",
        header: t("slug"),
        sortable: true,
        cell: (org) => <span className="text-muted-foreground font-mono text-xs">{org.slug}</span>,
      },
      {
        key: "members",
        header: t("members"),
        align: "right",
        sortable: true,
        cell: (org) => <span className="tabular-nums">{org.member_count}</span>,
      },
      {
        key: "agents",
        header: t("agents2"),
        align: "right",
        sortable: true,
        cell: (org) => <span className="tabular-nums">{org.agent_count}</span>,
      },
      {
        key: "created_at",
        header: t("created"),
        align: "right",
        className: "pr-5",
        sortable: true,
        cell: (org) => (
          <span className="text-muted-foreground text-xs">
            {formatDate(org.created_at, locale)}
          </span>
        ),
      },
    ],
    [t, locale],
  );

  return (
    <ListCard
      title={t("organizations2")}
      counted={isLoading && organizations.length === 0 ? null : t("totalCount", { count: total })}
      controls={
        <div className="flex flex-wrap items-center gap-2">
          <Select value={kind} onValueChange={(value) => setKind(value as AdminOrgKind)}>
            <SelectTrigger className="w-44" aria-label={t("filterByKind")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KINDS.map((entry) => (
                <SelectItem key={entry.value} value={entry.value}>
                  {t(entry.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchOrganizations")} />
        </div>
      }
      contentClassName="p-0"
    >
      <DataTable<AdminOrganization>
        columns={columns}
        rows={organizations}
        getRowKey={(org) => org.id}
        loading={isLoading && organizations.length === 0}
        skeletonRows={4}
        sort={sort}
        onSort={setSort}
        error={
          error ? (
            <ErrorState description={t("organizationsCouldNotBeRead")} className="m-5" />
          ) : null
        }
        empty={term ? t("noOrganizationsMatch", { query: term }) : t("noOrganizationsYet")}
        className="rounded-none border-0 bg-transparent [&_table]:min-w-[36rem]"
      />

      {total > 0 && (
        <ListCardFootRow>
          <PaginationBar
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            isLoading={isLoading}
            onPage={setPage}
          />
        </ListCardFootRow>
      )}
    </ListCard>
  );
}
