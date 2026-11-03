"use client";
import { useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Panel } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { FileViewer } from "@/components/files";
import { useWikiGraph } from "@/hooks/use-wiki-graph";
import { useWorkspaceFullscreen } from "@/hooks/use-workspace-fullscreen";
import { textKey, bytesKey, workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import { wikiColour, wikiGroup, wikiGroups } from "@/lib/wiki-flow";
import type { WikiGraph } from "@/lib/wiki-graph";
import { cn } from "@/lib/utils";
import { WikiCanvas } from "./wiki-canvas";
import { WikiToolbar } from "./wiki-toolbar";
import { WikiInspector } from "./wiki-inspector";
import { WikiDiagnostics } from "./wiki-diagnostics";

const EMPTY_GRAPH: WikiGraph = { pages: [], edges: [], unresolved: [] };
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
  const pages = useMemo(
    () =>
      graph.pages.filter((page) =>
        [page.title, page.path, ...page.tags, ...page.aliases].some((value) =>
          value.toLowerCase().includes(search.toLowerCase().replace(/^#/, "")),
        ),
      ),
    [graph, search],
  );
  const visible = useMemo(() => new Set(pages.map((page) => page.path)), [pages]);
  const groups = useMemo(() => wikiGroups(graph.pages), [graph]);
  const page = graph.pages.find((entry) => entry.path === selected);
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
            onNotes={() => setNotesOpen(!notesOpen)}
            onRefresh={() => void query.refetch()}
            expanded={expanded}
            onExpand={toggle}
            onClose={onClose}
          />
        </Panel>
        {(notesOpen || search) && (
          <Panel position="top-left" className="!top-28 !left-3 !m-0 sm:!top-20">
            <aside
              className="bg-card/95 w-64 overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl"
              aria-label={t("notes")}
            >
              <h3 className="border-b px-4 py-3 text-xs font-semibold">{t("notes")}</h3>
              <ul className="max-h-[35dvh] overflow-auto p-2 sm:max-h-[60dvh]">
                {pages.map((entry) => (
                  <li key={entry.path}>
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs"
                      aria-pressed={selected === entry.path}
                      title={entry.path}
                      onClick={() => {
                        setSelected(entry.path);
                        setNotesOpen(false);
                        setSearch("");
                      }}
                    >
                      <span
                        className="size-2 shrink-0 rounded-full"
                        style={{ background: wikiColour(wikiGroup(entry), groups) }}
                      />
                      <span className="truncate">{entry.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {pages.length === 0 && (
                <p className="text-muted-foreground p-4 text-xs">{t("noMatches")}</p>
              )}
            </aside>
          </Panel>
        )}
        {page && (
          <Panel
            position="top-right"
            className="!top-auto !right-3 !bottom-16 !left-3 !m-0 sm:!top-20 sm:!bottom-auto sm:!left-auto sm:!w-80"
          >
            <WikiInspector
              page={page}
              colour={wikiColour(wikiGroup(page), groups)}
              graph={graph}
              onSelect={setSelected}
              onOpen={(path) => void open(path)}
              onClose={() => setSelected(null)}
              renderEditor={renderEditor}
            />
          </Panel>
        )}
        <Panel position="bottom-left" className="!right-44 !bottom-3 !left-3 !m-0">
          <div className="bg-card/95 max-h-36 max-w-lg space-y-2 overflow-auto rounded-xl border px-3 py-2 text-xs shadow-lg backdrop-blur-xl">
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
                  {group}
                </span>
              ))}
            </div>
            {snapshot && <WikiDiagnostics graph={snapshot} />}
          </div>
        </Panel>
      </WikiCanvas>
      {opened && graph.pages.some((entry) => entry.path === opened) && (
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
