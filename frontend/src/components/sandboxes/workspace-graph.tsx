"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { FileViewer } from "@/components/files";
import { WikiCanvas } from "./wiki-canvas";
import { useWikiGraph } from "@/hooks/use-wiki-graph";
import { textKey, bytesKey, workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import type { WikiGraph } from "@/lib/wiki-graph";

export function WorkspaceGraph({
  source,
  renderEditor,
}: {
  source: FileSource;
  renderEditor?: (path: string) => ReactNode;
}) {
  const t = useTranslations("wikiGraph");
  const query = useWikiGraph(source);
  const client = useQueryClient();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const graph = query.error ? undefined : query.data;
  const pages = useMemo(
    () =>
      graph?.pages.filter((page) =>
        [page.title, page.path, ...page.tags, ...page.aliases].some((value) =>
          value.toLowerCase().includes(search.toLowerCase().replace(/^#/, "")),
        ),
      ) ?? [],
    [graph, search],
  );
  const visible = useMemo(() => new Set(pages.map((page) => page.path)), [pages]);
  const page = graph?.pages.find((page) => page.path === selected);
  const open = async (path: string) => {
    await Promise.all([
      client.invalidateQueries({ queryKey: textKey(source, path) }),
      client.invalidateQueries({ queryKey: bytesKey(source, path) }),
    ]);
    setOpened(path);
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          aria-label={t("search")}
          placeholder={t("search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="max-w-sm"
        />
        <Button
          variant="outline"
          size="sm"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          <RefreshCw className="size-4" aria-hidden />
          {t("refresh")}
        </Button>
        <span role="status" className="text-muted-foreground text-xs">
          {query.isFetching ? t("loading") : t("automatic")}
        </span>
      </div>
      {query.error && (
        <p role="alert" className="text-destructive text-sm">
          {t("failed")}
        </p>
      )}
      {graph && (
        <>
          <p className="text-muted-foreground text-xs">
            {t("counts", { pages: graph.pages.length, links: graph.edges.length })}
          </p>
          {(graph.skipped.length > 0 || graph.failed.length > 0 || graph.truncated) && (
            <details className="text-sm">
              <summary>{t("partial")}</summary>
              <p>{t("limits")}</p>
              <ul>
                {graph.skipped.map((path) => (
                  <li key={path}>{t("skipped", { path })}</li>
                ))}
                {graph.failed.map((path) => (
                  <li key={path}>{t("unreadable", { path })}</li>
                ))}
              </ul>
            </details>
          )}
          {graph.pages.some((entry) => entry.invalidFrontmatter) && (
            <p role="alert" className="text-sm">
              {t("invalidFrontmatter", {
                paths: graph.pages
                  .filter((entry) => entry.invalidFrontmatter)
                  .map((entry) => entry.path)
                  .join(", "),
              })}
            </p>
          )}
          {graph.pages.length === 0 ? (
            <p className="text-muted-foreground py-12 text-center">{t("empty")}</p>
          ) : (
            <div className="grid min-h-0 flex-1 gap-4 overflow-auto lg:grid-cols-[1fr_18rem] lg:overflow-visible">
              <WikiCanvas
                graph={graph}
                visible={visible}
                selected={page?.path ?? null}
                onSelect={setSelected}
              />
              <div className="flex min-h-72 flex-col gap-4 overflow-auto rounded-xl border p-3 lg:min-h-0">
                {page && (
                  <section className="space-y-2">
                    <h3 className="font-medium">{page.title}</h3>
                    <p className="text-muted-foreground text-xs break-all">{page.path}</p>
                    <p className="text-muted-foreground text-xs">
                      {page.tags.map((tag) => `#${tag}`).join(" ")}
                    </p>
                    <div className="flex flex-wrap gap-1">
                      <Button size="sm" variant="outline" onClick={() => void open(page.path)}>
                        {t("open")}
                      </Button>
                      {renderEditor?.(page.path)}
                    </div>
                    <Connections graph={graph} path={page.path} onSelect={setSelected} />
                  </section>
                )}
                <section>
                  <h3 className="mb-2 text-sm font-medium">{t("notes")}</h3>
                  {pages.length === 0 && (
                    <p className="text-muted-foreground text-sm">{t("noMatches")}</p>
                  )}
                  <ul className="space-y-1">
                    {pages.map((entry) => (
                      <li key={entry.path}>
                        <button
                          type="button"
                          className="hover:bg-accent w-full rounded px-2 py-1 text-left text-sm break-words"
                          aria-pressed={selected === entry.path}
                          title={entry.path}
                          onClick={() => setSelected(entry.path)}
                        >
                          {entry.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </div>
          )}
          {opened && graph.pages.some((entry) => entry.path === opened) && (
            <FileViewer
              key={opened}
              file={{ name: opened.split("/").at(-1) ?? opened, path: opened }}
              access={workspaceFileAccess(source, opened)}
              onClose={() => setOpened(null)}
            />
          )}
        </>
      )}
    </div>
  );
}

function Connections({
  graph,
  path,
  onSelect,
}: {
  graph: WikiGraph;
  path: string;
  onSelect: (path: string) => void;
}) {
  const t = useTranslations("wikiGraph");
  return (
    <div className="space-y-3 text-sm">
      {(["outgoing", "backlinks"] as const).map((direction) => {
        const edges = graph.edges.filter((edge) =>
          direction === "outgoing" ? edge.source === path : edge.target === path,
        );
        return (
          <section key={direction}>
            <h4 className="text-muted-foreground mb-1 text-xs">{t(direction)}</h4>
            <ul>
              {edges.map((edge) => {
                const target = direction === "outgoing" ? edge.target : edge.source;
                return (
                  <li key={target}>
                    <button
                      type="button"
                      className="text-primary break-all hover:underline"
                      onClick={() => onSelect(target)}
                    >
                      {target}
                    </button>
                  </li>
                );
              })}
            </ul>
            {edges.length === 0 && <p className="text-muted-foreground">{t("none")}</p>}
          </section>
        );
      })}
      {graph.unresolved.some((link) => link.source === path) && (
        <section>
          <h4 className="text-muted-foreground mb-1 text-xs">{t("unresolved")}</h4>
          <ul>
            {graph.unresolved
              .filter((link) => link.source === path)
              .map((link) => (
                <li className="break-all" key={link.target}>
                  {t(link.reason, { target: link.target })}
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  );
}
