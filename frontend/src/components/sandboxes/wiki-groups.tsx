"use client";

import { Eye, EyeOff, Folder, Hash } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { wikiColour, wikiGroup, type WikiGrouping } from "@/lib/wiki-flow";
import type { WikiPage } from "@/lib/wiki-graph";

export function WikiGroups({
  pages,
  groups,
  grouping,
  hidden,
  visible,
  onGrouping,
  onToggle,
  onReset,
}: {
  pages: readonly WikiPage[];
  groups: readonly string[];
  grouping: WikiGrouping;
  hidden: ReadonlySet<string>;
  visible: number;
  onGrouping: (mode: WikiGrouping) => void;
  onToggle: (group: string) => void;
  onReset: () => void;
}) {
  const t = useTranslations("wikiGraph");
  return (
    <aside
      className="bg-card/95 w-72 overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl"
      aria-label={t("groups")}
    >
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-xs font-semibold">{t("groups")}</h3>
        <Button size="sm" variant="ghost" onClick={onReset}>
          {t("resetFilters")}
        </Button>
      </div>
      <div className="space-y-3 p-3">
        <p className="text-muted-foreground text-[11px]">{t("groupBy")}</p>
        <div
          className="bg-muted/60 flex gap-1 rounded-lg p-1"
          role="group"
          aria-label={t("groupBy")}
        >
          <Button
            size="sm"
            className="flex-1"
            variant={grouping === "folder" ? "secondary" : "ghost"}
            aria-pressed={grouping === "folder"}
            onClick={() => onGrouping("folder")}
          >
            <Folder className="size-3.5" aria-hidden />
            {t("folders")}
          </Button>
          <Button
            size="sm"
            className="flex-1"
            variant={grouping === "tag" ? "secondary" : "ghost"}
            aria-pressed={grouping === "tag"}
            onClick={() => onGrouping("tag")}
          >
            <Hash className="size-3.5" aria-hidden />
            {t("tags")}
          </Button>
        </div>
        <ul className="max-h-[30dvh] space-y-1 overflow-auto">
          {groups.map((group) => (
            <li key={group}>
              <button
                type="button"
                aria-pressed={!hidden.has(group)}
                aria-label={t("toggleGroup", {
                  group:
                    group === "/" ? t(grouping === "folder" ? "rootFolder" : "untagged") : group,
                })}
                className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs"
                onClick={() => onToggle(group)}
              >
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{
                    background: wikiColour(group, groups),
                    opacity: hidden.has(group) ? 0.25 : 1,
                  }}
                />
                {grouping === "folder" ? (
                  <Folder className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
                ) : (
                  <Hash className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
                )}
                <span className="flex-1 truncate" title={group}>
                  {group === "/" ? t(grouping === "folder" ? "rootFolder" : "untagged") : group}
                </span>
                <span className="text-muted-foreground text-[10px]">
                  {pages.filter((page) => wikiGroup(page, grouping) === group).length}
                </span>
                {hidden.has(group) ? (
                  <EyeOff className="text-muted-foreground size-3" aria-hidden />
                ) : (
                  <Eye className="text-muted-foreground size-3" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground border-t pt-3 text-[11px]">
          {t("visibleNotes", { visible, total: pages.length })}
        </p>
      </div>
    </aside>
  );
}
