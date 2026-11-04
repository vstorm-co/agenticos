"use client";

import { useMemo, useState } from "react";
import { Filter, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { FileIcon, PathTree } from "@/components/files";
import { treeOf } from "@/lib/workspace-tree";
import type { WorkspaceFile } from "@/lib/sandbox-workspaces-api";
import type { WikiPage } from "@/lib/wiki-graph";
import { wikiColour, wikiGroup, type WikiGrouping } from "@/lib/wiki-flow";

export function WikiNavigator({
  files,
  pages,
  groups,
  grouping,
  search,
  folder,
  selected,
  onSelect,
  onFolder,
}: {
  files: WorkspaceFile[];
  pages: readonly WikiPage[];
  groups: readonly string[];
  grouping: WikiGrouping;
  search: string;
  folder: string | null;
  selected: string | null;
  onSelect: (path: string) => void;
  onFolder: (path: string | null) => void;
}) {
  const t = useTranslations("wikiGraph");
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const matched = useMemo(() => {
    const query = search.trim().toLowerCase().replace(/^#/, "");
    const indexed = new Map(pages.map((page) => [page.path, page]));
    return files.filter((file) => {
      const page = indexed.get(file.path);
      return (
        !query ||
        [file.path, page?.title, ...(page?.tags ?? []), ...(page?.aliases ?? [])].some((value) =>
          value?.toLowerCase().includes(query),
        )
      );
    });
  }, [files, pages, search]);
  const tree = useMemo(() => treeOf(matched), [matched]);
  const opened = new Set<string>();
  const collect = (nodes: typeof tree) => {
    for (const node of nodes)
      if (node.isDir) {
        if (!closed.has(node.path)) opened.add(node.path);
        collect(node.children);
      }
  };
  collect(tree);
  const indexed = new Map(pages.map((page) => [page.path, page]));
  return (
    <aside
      className="bg-card/95 w-72 overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl"
      aria-label={t("notes")}
    >
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-xs font-semibold">{t("fileBrowser")}</h3>
        <Button size="sm" variant="ghost" onClick={() => onFolder(null)}>
          {t("allFiles")}
        </Button>
      </div>
      {folder && (
        <div className="bg-muted/50 flex items-center gap-2 border-b px-3 py-2 text-xs">
          <Filter className="size-3 shrink-0" aria-hidden />
          <span className="flex-1 truncate" title={folder}>
            {folder}
          </span>
          <Button
            size="icon"
            variant="ghost"
            className="size-6"
            aria-label={t("clearFolder")}
            onClick={() => onFolder(null)}
          >
            <X className="size-3" />
          </Button>
        </div>
      )}
      <div className="max-h-[35dvh] overflow-auto p-2 sm:max-h-[55dvh]">
        <PathTree
          nodes={tree}
          label={t("fileBrowser")}
          selectedPath={selected}
          onSelect={(node) => onSelect(node.path)}
          openPaths={opened}
          onToggleFolder={(path) =>
            setClosed((previous) => {
              const next = new Set(previous);
              if (!next.delete(path)) next.add(path);
              return next;
            })
          }
          renderFile={(node) => (
            <>
              <FileIcon name={node.label} className="text-muted-foreground size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-[13px]">{node.label}</span>
            </>
          )}
          renderFileMeta={(node) => {
            const page = indexed.get(node.path);
            return page ? (
              <span
                className="mr-2 size-2 shrink-0 rounded-full"
                style={{ background: wikiColour(wikiGroup(page, grouping), groups) }}
              />
            ) : null;
          }}
          renderFolderMeta={(node) => (
            <Button
              size="icon"
              variant={folder === node.path ? "secondary" : "ghost"}
              className="mr-1 size-7"
              aria-label={t("filterFolder", { path: node.path })}
              onClick={() => onFolder(node.path)}
            >
              <Filter className="size-3" />
            </Button>
          )}
        />
        {tree.length === 0 && <p className="text-muted-foreground p-3 text-xs">{t("noMatches")}</p>}
      </div>
      <p className="text-muted-foreground border-t px-4 py-3 text-[11px] leading-relaxed">
        {t("fileBrowserHint")}
      </p>
    </aside>
  );
}
