"use client";
import { useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Panel } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { FileViewer } from "@/components/files";
import { useWikiGraph } from "@/hooks/use-wiki-graph";
import { useWorkspaceFullscreen } from "@/hooks/use-workspace-fullscreen";
import { textKey, bytesKey, workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import { wikiColour, wikiGroup, wikiGroups, type WikiGrouping } from "@/lib/wiki-flow";
import type { WikiGraph } from "@/lib/wiki-graph";
import { cn } from "@/lib/utils";
import { WikiCanvas } from "./wiki-canvas";
import { WikiToolbar } from "./wiki-toolbar";
import { WikiInspector } from "./wiki-inspector";
import { filterWikiPages, inWikiFolder } from "@/lib/wiki-navigation";
import { WikiNavigator } from "./wiki-navigator";
import { WikiGroups } from "./wiki-groups";
import { WikiDiagnostics } from "./wiki-diagnostics";

const EMPTY_GRAPH: WikiGraph = {
  pages: [],
  edges: [],
  unresolved: [],
  relationshipsTruncated: false,
  metadataTruncated: false,
};
export function WorkspaceGraph({
  source,
  renderEditor,
  onClose,
}: {
  source: FileSource;
  renderEditor?: (path: string) => ReactNode;
  onClose: () => void;
}) {
  const t = useTranslations("wikiGraph");
  const query = useWikiGraph(source);
  const client = useQueryClient();
  const { ref, expanded, toggle } = useWorkspaceFullscreen(true);
  const [search, setSearch] = useState("");
  const [notesOpen, setNotesOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const snapshot = query.error ? undefined : query.data;
  const graph = snapshot ?? EMPTY_GRAPH;
  const [grouping, setGrouping] = useState<WikiGrouping>("folder");
  const [hiddenGroups, setHiddenGroups] = useState<ReadonlySet<string>>(new Set());
  const [folder, setFolder] = useState<string | null>(null);
  const [groupsOpen, setGroupsOpen] = useState(true);
  const pages = useMemo(
    () => filterWikiPages(graph.pages, search, folder, hiddenGroups, grouping),
    [graph, search, folder, hiddenGroups, grouping],
  );
  const visible = useMemo(() => new Set(pages.map((page) => page.path)), [pages]);
  const groups = useMemo(() => wikiGroups(graph.pages, grouping), [graph, grouping]);
  const select = (path: string) => {
    const note = graph.pages.find((entry) => entry.path === path);
    if (!note) {
      void open(path);
      return;
    }
    setSelected(path);
    setSearch("");
    if (!inWikiFolder(path, folder)) setFolder(null);
    setHiddenGroups((previous) => {
      const next = new Set(previous);
      next.delete(wikiGroup(note, grouping));
      return next;
    });
  };
  const page = graph.pages.find((entry) => entry.path === selected && visible.has(entry.path));
  const open = async (path: string) => {
    await Promise.all([
      client.invalidateQueries({ queryKey: textKey(source, path) }),
      client.invalidateQueries({ queryKey: bytesKey(source, path) }),
    ]);
    setOpened(path);
  };
  return (
    <div
      ref={ref}
      data-expanded={expanded}
      className={cn(
        "bg-background relative min-h-[36rem] min-w-0 flex-1 overflow-hidden rounded-2xl border",
        expanded && "fixed inset-0 z-40 h-dvh min-h-0 rounded-none border-0",
      )}
    >
      <WikiCanvas
        graph={graph}
        visible={visible}
        selected={page?.path ?? null}
        onSelect={setSelected}
        grouping={grouping}
      >
        <Panel position="top-left" className="!right-3 !left-3 !m-0 !mt-3 sm:!right-auto">
          <WikiToolbar
            search={search}
            onSearch={(value) => {
              setSearch(value);
              if (value) setNotesOpen(true);
            }}
            count={graph.pages.length}
            links={graph.edges.length}
            busy={query.isFetching}
            notesOpen={notesOpen}
            onNotes={() => {
              setNotesOpen(!notesOpen);
              if (!notesOpen) setSelected(null);
            }}
            groupsOpen={groupsOpen && !page}
            onGroups={() => {
              setNotesOpen(false);
              setSearch("");
              if (page) {
                setSelected(null);
                setGroupsOpen(true);
              } else setGroupsOpen(!groupsOpen);
            }}
            onRefresh={() => void query.refetch()}
            expanded={expanded}
            onExpand={toggle}
            onClose={onClose}
          />
        </Panel>
        {(notesOpen || search) && (
          <Panel
            position="top-left"
            className={cn("!top-28 !left-3 !m-0 sm:!top-20", page && "!hidden sm:!block")}
          >
            <WikiNavigator
              files={snapshot?.files ?? []}
              pages={graph.pages}
              groups={groups}
              grouping={grouping}
              search={search}
              folder={folder}
              selected={opened ?? selected}
              onSelect={select}
              onFolder={setFolder}
            />
          </Panel>
        )}
        {(page || groupsOpen) && (
          <Panel
            position="top-right"
            className={cn(
              "!top-auto !right-3 !bottom-28 !left-3 !m-0 sm:!top-20 sm:!bottom-auto sm:!left-auto sm:!w-80",
              !page && (notesOpen || search) && "!hidden sm:!block",
            )}
          >
            {page ? (
              <WikiInspector
                page={page}
                colour={wikiColour(wikiGroup(page, grouping), groups)}
                graph={graph}
                onSelect={select}
                onOpen={(path) => void open(path)}
                onClose={() => setSelected(null)}
                renderEditor={renderEditor}
              />
            ) : (
              <WikiGroups
                pages={graph.pages}
                groups={groups}
                grouping={grouping}
                hidden={hiddenGroups}
                visible={pages.length}
                onGrouping={(mode) => {
                  setGrouping(mode);
                  setHiddenGroups(new Set());
                }}
                onToggle={(group) =>
                  setHiddenGroups((previous) => {
                    const next = new Set(previous);
                    if (!next.delete(group)) next.add(group);
                    return next;
                  })
                }
                onReset={() => {
                  setHiddenGroups(new Set());
                  setFolder(null);
                  setSearch("");
                }}
              />
            )}
          </Panel>
        )}
        <Panel
          position="bottom-left"
          className="!pointer-events-none !right-44 !bottom-3 !left-3 !m-0"
        >
          <div className="bg-card/95 pointer-events-auto max-h-36 max-w-lg space-y-2 overflow-auto rounded-xl border px-3 py-2 text-xs shadow-lg backdrop-blur-xl">
            <p role="status" className="text-muted-foreground text-[10px]">
              {query.isFetching ? t("loading") : t("automatic")}
            </p>
            {query.error ? (
              <p role="alert" className="text-destructive">
                {t("failed")}
              </p>
            ) : snapshot && graph.pages.length === 0 ? (
              <p>{t("empty")}</p>
            ) : null}
            <div className="hidden flex-wrap gap-x-3 gap-y-1 sm:flex">
              {groups.slice(0, 6).map((group) => (
                <span key={group} className="flex items-center gap-1.5 text-[10px]">
                  <span
                    className="size-2 rounded-full"
                    style={{ background: wikiColour(group, groups) }}
                  />
                  {group === "/" ? t(grouping === "folder" ? "rootFolder" : "untagged") : group}
                </span>
              ))}
            </div>
            {snapshot && <WikiDiagnostics graph={snapshot} />}
          </div>
        </Panel>
      </WikiCanvas>
      {opened && snapshot?.files.some((entry) => entry.path === opened && !entry.is_dir) && (
        <FileViewer
          key={opened}
          file={{ name: opened.split("/").at(-1) ?? opened, path: opened }}
          access={workspaceFileAccess(source, opened)}
          onClose={() => setOpened(null)}
        />
      )}
    </div>
  );
}
