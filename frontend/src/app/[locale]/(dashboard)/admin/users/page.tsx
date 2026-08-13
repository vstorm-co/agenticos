"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, Shield } from "lucide-react";

import { UserDetailDrawer } from "@/components/admin/user-detail-drawer";
import { ErrorState } from "@/components/states";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Badge,
  Button,
  DataTable,
  Input,
  PaginationBar,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import { useAdminUsers, useUrlSort } from "@/hooks";
import type { AdminUser } from "@/types";
import { formatDate } from "@/lib/utils";
import { useChanged } from "@/hooks/use-changed";

import { useLocale, useTranslations } from "next-intl";
const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
// Keys the backend can sort on (route → service → repo).
const SORT_KEYS = ["email", "full_name", "conversations", "created_at"] as const;

function getInitials(nameOrEmail: string): string {
  return nameOrEmail
    .split(/[\s@]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");
}

export default function AdminUsersPage() {
  const t = useTranslations("pages.admin");
  const tc = useTranslations("common");
  const locale = useLocale();
  const { users, total, isLoading, error, fetchUsers, updateUser, deleteUser, impersonateUser } =
    useAdminUsers();
  const [search, setSearch] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(0);
  const { sort, setSort } = useUrlSort(SORT_KEYS, { by: "created_at", dir: "desc" });
  // The id, not the row. Holding the object meant it went stale the moment the
  // list refetched, which an effect then copied back over - a second render
  // every time, to arrive where deriving it gets in one.
  const [drawerUserId, setDrawerUserId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerUser = users.find((u) => u.id === drawerUserId) ?? null;

  // Back to the first page whenever the filters move - see the conversations
  // page for the same reasoning.
  if (useChanged(`${search}|${pageSize}|${sort.by}|${sort.dir}`)) {
    setPage(0);
  }

  const load = useCallback(
    (pg: number, q: string, ps: number, sortBy: string, sortDir: "asc" | "desc") => {
      fetchUsers({
        skip: pg * ps,
        limit: ps,
        search: q || undefined,
        sortBy,
        sortDir,
      });
    },
    [fetchUsers],
  );

  // Debounced fetch - the server does filtering, sorting, and pagination.
  useEffect(() => {
    const timer = setTimeout(() => {
      load(page, search, pageSize, sort.by, sort.dir);
    }, 300);
    return () => clearTimeout(timer);
  }, [load, page, search, pageSize, sort.by, sort.dir]);

  const handleOpenUser = useCallback((user: AdminUser) => {
    setDrawerUserId(user.id);
    setDrawerOpen(true);
  }, []);

  const columns = useMemo<Column<AdminUser>[]>(
    () => [
      {
        key: "email",
        header: t("user"),
        sortable: true,
        cell: (u) => (
          <div className="flex min-w-0 items-center gap-3">
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarImage src={`/api/users/avatar/${u.id}`} alt={u.email} />
              <AvatarFallback className="text-[10px]">
                {getInitials(u.full_name || u.email)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <p className="text-foreground truncate text-sm font-medium">
                  {u.full_name || u.email.split("@")[0]}
                </p>
                {/* The deployment superadmin, which is the only authority a user
                    row carries. There is no `users.role` since `0066` -
                    authority inside an organization is a membership row plus
                    the permission catalog, and neither is on this screen. */}
                {u.is_app_admin && (
                  <Badge variant="outline" className="shrink-0 gap-0.5 font-normal">
                    <Shield className="h-2.5 w-2.5" />
                    {t("app")}
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground truncate text-xs">{u.email}</p>
            </div>
          </div>
        ),
      },
      {
        key: "conversations",
        align: "right",
        hideBelow: "md",
        header: t("conversations"),
        sortable: true,
        // The count the list query has always paid a join for and nothing read.
        cell: (u) => <span className="tabular-nums">{u.conversation_count}</span>,
      },
      {
        key: "is_active",
        hideBelow: "sm",
        header: t("status"),
        cell: (u) =>
          u.is_active ? (
            <Badge
              variant="outline"
              className="border-border bg-foreground/5 text-foreground font-normal"
            >
              {t("active")}
            </Badge>
          ) : (
            <Badge variant="outline" className="border-border text-muted-foreground font-normal">
              {t("suspended")}
            </Badge>
          ),
      },
      {
        key: "created_at",
        hideBelow: "md",
        header: t("joined"),
        sortable: true,
        cell: (u) => (
          <span className="text-muted-foreground text-sm">{formatDate(u.created_at, locale)}</span>
        ),
      },
      {
        key: "actions",
        header: "",
        align: "right",
        className: "w-0",
        cell: (u) => (
          <Button
            variant="outline"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              handleOpenUser(u);
            }}
          >
            {t("inspect")}
          </Button>
        ),
      },
    ],
    [t, locale, handleOpenUser],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
          <Input
            placeholder={t("searchByEmailName")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>

        <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZE_OPTIONS.map((n) => (
              <SelectItem key={n} value={String(n)}>
                {tc("perPage", { count: n })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <span className="text-muted-foreground ml-auto text-xs">
          {t("totalCount", { count: total })}
        </span>
      </div>

      <DataTable<AdminUser>
        columns={columns}
        rows={users}
        getRowKey={(u) => u.id}
        loading={isLoading && users.length === 0}
        onRowClick={handleOpenUser}
        sort={sort}
        onSort={setSort}
        error={error ? <ErrorState description={error} /> : null}
        empty={search ? t("noUsersMatch", { query: search }) : t("noUsersYet")}
      />

      <PaginationBar
        page={page}
        pageSize={pageSize}
        total={total}
        isLoading={isLoading}
        onPage={setPage}
      />

      <UserDetailDrawer
        user={drawerUser}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onUpdate={updateUser}
        onDelete={deleteUser}
        onImpersonate={impersonateUser}
      />
    </div>
  );
}
