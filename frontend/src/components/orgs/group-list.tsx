"use client";

import { Pencil, Search, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { GroupIcon } from "@/components/groups/group-icon";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  IconButton,
  ListCard,
  ListCardEmpty,
  Pager,
  SearchInput,
  useListControls,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { getErrorMessage } from "@/lib/api-error";
import type { Group } from "@/types/groups";

interface GroupListProps {
  groups: Group[];
  isLoading: boolean;
  error: Error | null;
  canManage: boolean;
  onCreate: () => void;
  onEdit: (group: Group) => void;
  onDelete: (group: Group) => void;
  onOpenMembers: (group: Group) => void;
  onRetry?: () => void;
}

/** A department's identity and people stay together at every screen width. */
export function GroupList({
  groups,
  isLoading,
  error,
  canManage,
  onCreate,
  onEdit,
  onDelete,
  onOpenMembers,
  onRetry,
}: GroupListProps) {
  const t = useTranslations("groups");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const list = useListControls({
    items: groups,
    pageSize: 12,
    matches: (group, query) =>
      group.name.toLowerCase().includes(query) ||
      (group.description ?? "").toLowerCase().includes(query),
  });
  return (
    <ListCard
      fill
      namedByPage
      layout="grid"
      title={t("title")}
      counted={isLoading || error ? null : t("groupCount", { count: groups.length })}
      empty={!isLoading && !error && groups.length === 0}
      contentClassName="p-0"
      controls={
        groups.length > 0 &&
        !error && (
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("searchGroups")}
            className="w-full sm:w-64"
          />
        )
      }
    >
      {error ? (
        <ErrorState
          description={getErrorMessage(error, tErrors)}
          cta={onRetry ? { label: tc("retry"), onClick: onRetry } : undefined}
          className="m-5"
        />
      ) : isLoading ? (
        <LoadingState variant="skeleton-cards" rows={3} />
      ) : groups.length === 0 ? (
        <ListCardEmpty
          icon={Users}
          title={t("emptyTitle")}
          description={t("emptyBody")}
          cta={canManage ? { label: t("newGroup"), onClick: onCreate } : undefined}
        />
      ) : list.visible.length === 0 ? (
        <ListCardEmpty
          icon={Search}
          title={t("noMatches")}
          description={t("searchHint")}
          cta={{ label: t("clearSearch"), onClick: () => list.setQuery("") }}
        />
      ) : (
        <div className="space-y-4">
          <ul className="grid auto-rows-fr gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {list.visible.map((group) => (
              <li
                key={group.id}
                className="border-border bg-card hover:border-foreground/20 flex min-w-0 flex-col rounded-2xl border p-4 transition-colors"
              >
                <div className="flex flex-1 items-start gap-3">
                  <GroupIcon icon={group.icon} className="size-11 rounded-xl [&_svg]:size-5" />
                  <div className="min-w-0 flex-1">
                    <Link
                      href={ROUTES.GROUP_DETAIL(group.id)}
                      className="text-foreground text-sm font-semibold [overflow-wrap:anywhere] underline-offset-4 hover:underline"
                    >
                      {group.name}
                    </Link>
                    {group.description && (
                      <p
                        className="text-muted-foreground mt-1.5 line-clamp-3 text-[13px] leading-relaxed"
                        title={group.description}
                      >
                        {group.description}
                      </p>
                    )}
                  </div>
                </div>
                <div className="border-border mt-4 flex items-center justify-between gap-2 border-t pt-3">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="-ml-2 min-w-0"
                    onClick={() => onOpenMembers(group)}
                    aria-label={t("membersOf", { name: group.name })}
                  >
                    <Users aria-hidden className="size-4" />
                    {t("memberCount", { count: group.member_count })}
                  </Button>
                  {canManage && (
                    <div className="flex shrink-0 items-center gap-0.5">
                      <IconButton
                        onClick={() => onEdit(group)}
                        aria-label={t("editNamed", { name: group.name })}
                      >
                        <Pencil />
                      </IconButton>
                      <IconButton
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => onDelete(group)}
                        aria-label={tc("removeNamed", { name: group.name })}
                      >
                        <Trash2 />
                      </IconButton>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <Pager
            page={list.page}
            pageCount={list.pageCount}
            matched={list.matched}
            total={list.total}
            onPage={list.setPage}
            counted={t("groupCount", { count: list.total })}
          />
        </div>
      )}
    </ListCard>
  );
}
