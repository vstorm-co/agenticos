"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus, Table2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { CreateTableDialog } from "@/components/tables/create-table-dialog";
import { TableCard } from "@/components/tables/table-card";
import {
  Button,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  PaginationBar,
  SearchInput,
  Skeleton,
  useDebounced,
} from "@/components/ui";
import { useTables, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

export default function TablesPage() {
  const t = useTranslations("pages.tables");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const { tables, total, isLoading, create } = useTables({
    search,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can } = usePermissions();
  const canCreate = can(Perm.tablesCreate);
  const [createOpen, setCreateOpen] = useState(false);
  const router = useRouter();

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate ? (
            <Button data-tour="tables-new" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> {t("newTable")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        title={t("catalog")}
        counted={isLoading ? null : t("shownCount", { count: total })}
        controls={
          <SearchInput
            value={query}
            onChange={(next) => {
              setQuery(next);
              setPage(0);
            }}
            placeholder={t("searchPlaceholder")}
          />
        }
        data-tour="tables-catalog"
      >
        {isLoading && tables.length === 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-36 w-full rounded-xl" />
            ))}
          </div>
        ) : tables.length === 0 ? (
          <ListCardEmpty
            icon={Table2}
            title={search ? t("empty.filteredTitle") : t("empty.title")}
            description={search ? undefined : t("empty.description")}
            cta={
              canCreate && !search
                ? { label: t("newTable"), onClick: () => setCreateOpen(true) }
                : undefined
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {tables.map((table) => (
              <TableCard key={table.id} table={table} />
            ))}
          </div>
        )}
      </ListCard>

      <div>
        <PaginationBar
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          isLoading={isLoading}
          onPage={setPage}
        />
      </div>

      <CreateTableDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreate={(input) =>
          create.mutate(input, {
            onSuccess: (table) => {
              setCreateOpen(false);
              router.push(ROUTES.TABLE_DETAIL(table.id));
            },
          })
        }
        isCreating={create.isPending}
        error={create.error}
      />
    </div>
  );
}
