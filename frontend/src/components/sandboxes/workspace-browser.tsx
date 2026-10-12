"use client";

import { useMemo, useState } from "react";
import { Download, FolderOpen } from "lucide-react";

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
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FileCard, FileViewer } from "@/components/files";
import { useAllWorkspaceFiles } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { suffixOf } from "@/lib/file-kinds";
import { workspaceFileAccess } from "@/lib/workspace-files";
import { cn } from "@/lib/utils";
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
function compareFlat(sort: FlatSort, a: FlatFile, b: FlatFile): number {
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
  const t = useTranslations("sandboxes");
  // The same query the list below reads, so the count costs no second request.
  const { listing, isLoading } = useAllWorkspaceFiles(true);
  return (
    <ListCard
      title={t("workspaces.allFiles")}
      counted={isLoading ? null : t("fileCount", { count: listing?.total ?? 0 })}
      contentClassName="p-0"
    >
      <FlatFiles />
    </ListCard>
  );
}

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
  const tc = useTranslations("common");
  const { listing, isLoading, error } = useAllWorkspaceFiles(true);
  const [opened, setOpened] = useState<FlatFile | null>(null);
  const [sort, setSort] = useState<FlatSort>("name");
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

  if (isLoading) return <Skeleton className="m-5 h-24" />;
  if (error !== null) return <p className="text-destructive px-5 py-4 text-sm">{error}</p>;
  if (listing === null) return null;

  if (listing.items.length === 0)
    return (
      <ListCardEmpty
        icon={FolderOpen}
        title={t("noAgentHoldingFile")}
        description={t("noAgentHoldingFileWhy")}
        cta={{ label: t("openAgents"), onClick: () => router.push(ROUTES.AGENTS) }}
      />
    );

  return (
    <div className="space-y-3 p-5">
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
      </div>
      {list.matched === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">{t("noFileMatches")}</p>
      ) : (
        /* Tiles rather than rows, on the card every other surface shows a file
           as - so a CSV looks like the same thing here, in the chat panel and in
           the composer. The card carries the preview or the thumbnail, the
           suffix and the size;
           the line under it carries what only this view knows: the agent holding
           the file and who else can see it. */
        <ul className="rise-in grid grid-cols-1 items-start gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {list.visible.map((file) => (
            <li key={key(file)} className="space-y-1">
              <FileCard
                name={file.path}
                size={file.size}
                preview={file.preview}
                imageUrl={file.thumbnail}
                onOpen={() => setOpened(file)}
                className="w-full"
              />
              {/* Said on the tile rather than only filterable: a PDF a person
                  attached and a PDF an agent produced are read for different
                  reasons, and the path is not always the answer - `report.csv` at
                  a workspace root could be either. */}
              <p className="text-muted-foreground flex items-center gap-1 px-1 text-xs">
                <span
                  className={cn(
                    "shrink-0 rounded px-1 py-0.5 text-xs",
                    file.from_upload ? "bg-accent text-foreground" : "text-muted-foreground",
                  )}
                >
                  {file.from_upload ? t("workspaces.fromMe") : t("workspaces.fromTheAgent")}
                </span>
                <Link
                  href={ROUTES.DOCUMENT_FOLDER(file.workspace_id)}
                  className="truncate hover:underline"
                >
                  {file.agent_name}
                </Link>
                <span className="truncate">· {file.access_label}</span>
                <button
                  type="button"
                  aria-label={tc("downloadNamed", { name: file.path })}
                  onClick={() =>
                    void workspaceFileAccess(
                      { kind: "workspace", id: file.workspace_id },
                      file.path,
                    ).download()
                  }
                  className="hover:text-foreground ml-auto shrink-0 rounded-md p-1"
                >
                  <Download className="h-3.5 w-3.5" />
                </button>
              </p>
            </li>
          ))}
        </ul>
      )}
      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        counted={t("fileCount", { count: list.total })}
      />
      {opened !== null && (
        <FileViewer
          file={{
            name: opened.path.split("/").filter(Boolean).pop() ?? opened.path,
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
