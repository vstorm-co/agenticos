"use client";

import { useMemo, useState } from "react";
import { FolderOpen } from "lucide-react";

import {
  ListCard,
  ListCardEmpty,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  useListControls,
} from "@/components/ui";
import { useRouter } from "next/navigation";

import { FileViewer } from "@/components/files";
import { DocumentTile } from "@/components/sandboxes/document-tile";
import { groupByWorkspace, WorkspaceGroups } from "@/components/sandboxes/workspace-groups";
import { useAllWorkspaceFiles } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { suffixOf } from "@/lib/file-kinds";
import { documentName, workspaceFileAccess } from "@/lib/workspace-files";
import type { FlatFile } from "@/lib/sandbox-workspaces-api";
import { useTranslations } from "next-intl";

/** One file's identity across workspaces: the same path exists in several.
 *  The separator matters - without it `{w:"ab", p:"c"}` and `{w:"a", p:"bc"}`
 *  collide into one React key. */
function key(file: { workspace_id: string; path: string }): string {
  return `${file.workspace_id}:${file.path}`;
}

type FlatSort = "name" | "size" | "modified" | "agent";

/** Who put a file in the workspace, as the filter offers it. */
type Origin = "any" | "upload" | "agent";

/** Newest and biggest first: those orders answer "what changed" and "what is
 *  eating the quota", where a name orders alphabetically. */
export function compareFlat(sort: FlatSort, a: FlatFile, b: FlatFile): number {
  switch (sort) {
    case "size":
      return (b.size ?? -1) - (a.size ?? -1);
    case "modified": {
      const at = a.modified_at === null ? 0 : new Date(a.modified_at).getTime();
      const bt = b.modified_at === null ? 0 : new Date(b.modified_at).getTime();
      return bt - at;
    }
    case "agent":
      return a.agent_name.localeCompare(b.agent_name) || a.path.localeCompare(b.path);
    default:
      return a.path.localeCompare(b.path);
  }
}

/**
 * Every file agents are keeping for this reader, in one list.
 *
 * It used to open on a table of workspaces with a switch to this list, and the
 * list was what people came for: "where is that CSV" and "what did the agent
 * write" are the questions this page is opened with, and "which workspaces
 * exist" was an operator's question answered on a page that is everybody's. A
 * workspace is still one click away - each file names the agent holding it, and
 * that name opens the folder it sits in.
 *
 * Which files appear is the backend's decision, not this component's: an
 * operator sees the organization's, and everybody else sees the ones they are
 * part of.
 */
export function WorkspaceBrowser() {
  return <FlatFiles />;
}

/** How many of the newest files the Recent strip previews above the groups. */
const RECENT = 4;

/**
 * Every file at once, with the workspace each came from named beside it.
 *
 * The bound and the failures are shown rather than logged: a shorter list reads as
 * fewer files, so "we stopped looking" and "one host did not answer" have to be on
 * screen or the list is quietly a lie.
 */
function FlatFiles() {
  const t = useTranslations("sandboxes");
  const router = useRouter();
  const { listing, isLoading, error } = useAllWorkspaceFiles(true);
  const [opened, setOpened] = useState<FlatFile | null>(null);
  // Newest first: what an agent just made is what this page is opened for.
  const [sort, setSort] = useState<FlatSort>("modified");
  const [origin, setOrigin] = useState<Origin>("any");

  const sorted = useMemo(
    () =>
      [...(listing?.items ?? [])]
        // Who put the file there, which is the question this view is opened with
        // as often as "where is that CSV": a workspace holds what a person gave
        // the agent and what the agent produced, and they are read for different
        // reasons.
        .filter((file) =>
          origin === "any" ? true : origin === "upload" ? file.from_upload : !file.from_upload,
        )
        .sort((a, b) => compareFlat(sort, a, b)),
    [listing, sort, origin],
  );
  const list = useListControls({
    items: sorted,
    matches: (file, query) =>
      file.path.toLowerCase().includes(query) ||
      file.agent_name.toLowerCase().includes(query) ||
      suffixOf(file.path) === query.replace(/^\./, ""),
  });

  // Grouped by workspace until something is searched for: a search is after one
  // file wherever it is, and the groups would only scatter the matches.
  const grouped = list.query === "";
  const groups = useMemo(() => (grouped ? groupByWorkspace(sorted) : []), [grouped, sorted]);
  // A preview of what changed last, above the groups, when there is more than a
  // screen of it: the tiles that show a file's first lines earn their room here.
  const recent = useMemo(
    () =>
      grouped && sorted.length > RECENT
        ? [...sorted].sort((a, b) => compareFlat("modified", a, b)).slice(0, RECENT)
        : [],
    [grouped, sorted],
  );
  const download = (file: FlatFile) =>
    void workspaceFileAccess({ kind: "workspace", id: file.workspace_id }, file.path).download();

  if (isLoading) return <Skeleton className="m-5 h-24" />;
  if (error !== null) return <p className="text-destructive px-5 py-4 text-sm">{error}</p>;
  if (listing === null) return null;

  if (listing.items.length === 0)
    return (
      <ListCard fill namedByPage title={t("workspaces.allFiles")} counted={null} empty>
        <ListCardEmpty
          icon={FolderOpen}
          title={t("noAgentHoldingFile")}
          description={t("noAgentHoldingFileWhy")}
          cta={{ label: t("openAgents"), onClick: () => router.push(ROUTES.AGENTS) }}
        />
      </ListCard>
    );

  return (
    <div className="flex flex-1 flex-col space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchFiles")} />
        <Select value={origin} onValueChange={(value) => setOrigin(value as Origin)}>
          <SelectTrigger className="w-auto min-w-36" aria-label={t("workspaces.whoPutItThere")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">{t("workspaces.fromAnyone")}</SelectItem>
            <SelectItem value="upload">{t("workspaces.fromMe")}</SelectItem>
            <SelectItem value="agent">{t("workspaces.fromTheAgent")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(value) => setSort(value as FlatSort)}>
          <SelectTrigger className="w-auto min-w-36" aria-label={t("sortFiles")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="name">{t("sortByName")}</SelectItem>
            <SelectItem value="size">{t("sortBySize")}</SelectItem>
            <SelectItem value="modified">{t("sortByModified")}</SelectItem>
            <SelectItem value="agent">{t("sortByAgent")}</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-muted-foreground ml-auto text-xs">
          {t("fileCount", { count: listing.total })}
        </span>
      </div>
      {recent.length > 0 && (
        <section aria-label={t("workspaces.recent")} className="space-y-2.5">
          <h2 className="text-muted-foreground text-xs font-medium">{t("workspaces.recent")}</h2>
          {/* A strip that scrolls sideways on a phone: four cards stacked were the
              whole first screen before the first conversation. */}
          <ul className="-mx-1 flex snap-x scrollbar-none gap-3 overflow-x-auto px-1 pb-1 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 lg:grid-cols-4">
            {recent.map((file) => (
              <li key={key(file)} className="w-[78%] shrink-0 snap-start sm:w-auto">
                <DocumentTile
                  file={file}
                  onOpen={() => setOpened(file)}
                  onDownload={() => download(file)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
      {/* Nothing left after the origin filter says so, grouped or not: grouping
          an empty list drew no groups and no sentence - a blank results area. */}
      {list.matched === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">{t("noFileMatches")}</p>
      ) : grouped ? (
        <WorkspaceGroups groups={groups} onOpen={setOpened} onDownload={download} />
      ) : (
        /* Four across on a wide screen: a document is recognised by its first
           lines and its name, and a fourth column shows a quarter more of them
           before the first scroll. One card per file, with the agent holding it
           and where it came from inside the card rather than hung under it. */
        <ul className="rise-in grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {list.visible.map((file) => (
            <li key={key(file)}>
              <DocumentTile
                file={file}
                onOpen={() => setOpened(file)}
                onDownload={() => download(file)}
              />
            </li>
          ))}
        </ul>
      )}
      {!grouped && (
        <Pager
          page={list.page}
          pageCount={list.pageCount}
          matched={list.matched}
          total={list.total}
          onPage={list.setPage}
          counted={t("fileCount", { count: list.total })}
        />
      )}
      {opened !== null && (
        <FileViewer
          file={{
            name: documentName(opened.path, opened.from_upload),
            path: opened.path,
            size: opened.size,
            modifiedAt: opened.modified_at,
          }}
          access={workspaceFileAccess({ kind: "workspace", id: opened.workspace_id }, opened.path)}
          onClose={() => setOpened(null)}
        />
      )}
      {/* The bound and the failures stay on screen while a filter is applied: a
          filter over a truncated listing searched a sample, and "3 results" with
          no caveat would claim the search was exhaustive. */}
      {(listing.truncated || listing.unreadable > 0) && (
        <p className="text-muted-foreground text-xs">
          {listing.truncated && t("readSoManyWorkspaces", { count: listing.workspaces_read })}
          {listing.unreadable > 0 && t("someUnreadable", { count: listing.unreadable })}
          {listing.truncated && list.query !== "" && <> {t("filterSearchedASample")}</>}
        </p>
      )}
    </div>
  );
}
