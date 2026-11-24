"use client";

import { Pencil, Search, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { CatalogLoading } from "@/components/states/catalog-loading";
import { GroupIcon } from "@/components/groups/group-icon";
import { ErrorState } from "@/components/states";
import {
  Button,
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
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
        (isLoading || groups.length > 0) &&
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
        <div className="p-4 sm:p-5">
          <CatalogLoading kind="group" />
        </div>
      ) : groups.length === 0 ? (
        <ListCardEmpty
          icon={Users}
          title={t("emptyTitle")}
          description={t("emptyBody")}
          cta={canManage ? { label: t("newGroup"), onClick: onCreate } : undefined}
        />
      ) : list.visible.length === 0 ? (
        <ListCardEmpty
          onClearFilters={() => list.setQuery("")}
          icon={Search}
          title={t("noMatches")}
          description={t("searchHint")}
        />
      ) : (
        <div className="space-y-4">
          <ul className="grid auto-rows-fr gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {list.visible.map((group) => (
              <li key={group.id} className="min-w-0">
                <ResourceCard>
                  <ResourceCardHeader>
                    <GroupIcon icon={group.icon} className="size-11 rounded-xl [&_svg]:size-5" />
                    <div className="min-w-0 flex-1">
                      <Link
                        href={ROUTES.GROUP_DETAIL(group.id)}
                        className="text-foreground text-base font-semibold [overflow-wrap:anywhere] underline-offset-4 hover:underline"
                      >
                        {group.name}
                      </Link>
                    </div>
                  </ResourceCardHeader>
                  <ResourceCardDescription title={group.description ?? undefined}>
                    {group.description}
                  </ResourceCardDescription>
                  <ResourceCardFooter className="justify-between">
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
                  </ResourceCardFooter>
                </ResourceCard>
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
