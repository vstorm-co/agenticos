"use client";

import { useMemo, useState } from "react";
import { Download, MessageSquare } from "lucide-react";

import {
  Button,
  DataTable,
  ListCard,
  Pager,
  SearchInput,
  Switch,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  useListControls,
  type Column,
} from "@/components/ui";
import Link from "next/link";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { FileCard, FileViewer } from "@/components/files";
import { useAllWorkspaceFiles, useSandboxWorkspaces } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { suffixOf } from "@/lib/file-kinds";
import { workspaceFileAccess } from "@/lib/workspace-files";
import { formatBytes } from "@/lib/utils";
import type { FlatFile, WorkspaceSummary } from "@/lib/sandbox-workspaces-api";
import { useTranslations } from "next-intl";

/** One file's identity across workspaces: the same path exists in several.
 *  The separator matters - without it `{w:"ab", p:"c"}` and `{w:"a", p:"bc"}`
 *  collide into one React key. */
function key(file: { workspace_id: string; path: string }): string {
  return `${file.workspace_id}:${file.path}`;
}

type FlatSort = "name" | "size" | "modified" | "agent";

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
 * What identifies one workspace, in words.
 *
 * The conversation where there is one, because that is what an agent's twenty
 * workspaces differ by. A `run`- or `agent`-scoped workspace has no single chat,
 * so it leads with whose it is - which under `agent` scope is the whole point.
 */
function title(workspace: WorkspaceSummary, t: (key: string) => string): string {
  if (workspace.conversation_title !== null) return workspace.conversation_title;
  if (workspace.conversation_id !== null) return t("untitledChat");
  return workspace.owner_label;
}

/** When it was last touched, roughly. */
function used(when: string | null, t: (key: string, values?: Record<string, number>) => string) {
  if (when === null) return t("usedNever");
  const days = Math.floor((Date.now() - new Date(when).getTime()) / 86_400_000);
  if (days <= 0) return t("usedToday");
  if (days === 1) return t("usedYesterday");
  return t("usedDaysAgo", { days });
}

/**
 * The workspaces this reader can see, and the files in one.
 *
 * A workspace is scratch space, so a list of them is a list of what the agents are
 * *holding* — which is the question this answers and the conversation panel cannot:
 * a `run`-scoped workspace never had a conversation and an `agent`-scoped one
 * belongs to all of them, so neither is reachable from a chat.
 *
 * Which workspaces appear is the backend's decision, not this component's: an
 * operator sees the organization's, and everybody else sees the ones they are part
 * of. That is why this is no longer gated in the nav — a person's own files are not
 * an operator surface.
 *
 * `access_label` is a column and not decoration. Under `agent` scope one workspace
 * is shared by everybody who talks to that agent, and a table of paths with no
 * statement of who can see them is the wrong thing to hand somebody auditing this.
 */
export function WorkspaceBrowser() {
  const t = useTranslations("sandboxes.workspaces");
  // Counting the files in a container-backed workspace is a round trip to its
  // host, per workspace - so it is a switch rather than something the page pays for
  // on open. A stored workspace is counted either way, because its files arrived
  // with the row.
  const [measure, setMeasure] = useState(false);
  const { workspaces, unreadable, truncated, isLoading, error } = useSandboxWorkspaces(measure);
  const [flat, setFlat] = useState(false);

  /**
   * Four columns, not seven, and the row is the link.
   *
   * Seven columns of small grey text made a table nobody could scan, and three of
   * them were two halves of one fact: an agent and the chat its files belong to are
   * one identity, and what holds a workspace and who can see it are one answer
   * about reach. Folded, each cell carries a heading and its qualifier - which is
   * the shape every other listing in this product already uses (#1039).
   *
   * The trailing `Open` button is gone and the agent's name is the link instead -
   * a real one, so the URL can be copied, middle-clicked and sent, which this
   * page's own comment says is the point of a workspace having one. Deliberately
   * not a clickable row: every `onRowClick` in this codebase opens something in
   * place, and a router push from one would need next-intl's navigation for the
   * locale prefix, which is a provider this table has never needed.
   */
  const columns = useMemo<Column<WorkspaceSummary>[]>(
    () => [
      {
        key: "workspace",
        header: t("workspace"),
        className: "pl-5",
        sortable: true,
        sortValue: (workspace) => title(workspace, t),
        // **The chat is the heading, and the agent is under it.** It was the other
        // way round, which read as twenty rows called `jarvis`: an organization
        // runs a handful of agents and a great many conversations, so the agent is
        // the part every row shares and the conversation is the part that tells
        // them apart.
        cell: (workspace) => (
          <div className="flex min-w-0 items-center gap-3">
            {/* Decorative beside the agent it initials - the presentation every
                list of agents draws. */}
            <span aria-hidden>
              <AgentAvatar
                agentId={workspace.agent_id}
                name={workspace.agent_name}
                hasAvatar={workspace.agent_has_avatar}
                size="sm"
              />
            </span>
            <div className="min-w-0">
              <Link
                href={ROUTES.WORKSPACE_DETAIL(workspace.id)}
                className="text-foreground block truncate text-sm font-medium underline-offset-4 hover:underline"
              >
                {title(workspace, t)}
              </Link>
              <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
                <span className="truncate">{workspace.agent_name}</span>
                {/* How many chats reach these files, where that is not one. Under
                    `agent` scope it is the difference between "my files" and
                    "everybody's", and the heading above cannot carry it because
                    such a workspace has no single conversation to be named after. */}
                {workspace.conversation_id === null && workspace.conversations > 0 && (
                  <span className="shrink-0">
                    · {t("conversationCount", { count: workspace.conversations })}
                  </span>
                )}
                {/* The chat itself, for the reader's own thread only - anybody
                    else's would land on an empty sidebar dressed as the
                    conversation. An icon rather than the title again, which is
                    now the heading above it. */}
                {workspace.conversation_id !== null && workspace.conversation_is_mine && (
                  <Link
                    href={`${ROUTES.CHAT}?id=${workspace.conversation_id}`}
                    className="hover:text-foreground shrink-0"
                    aria-label={t("openTheChatBehindFiles")}
                  >
                    <MessageSquare className="h-3 w-3" aria-hidden />
                  </Link>
                )}
              </span>
            </div>
          </div>
        ),
      },
      {
        key: "whoCanSeeIt",
        header: t("whoCanSeeIt"),
        // The label alone. The `container` badge beside it repeated on every row
        // of a deployment that runs one kind of host - a column of one word,
        // twenty times, saying what `Where` now says once per row.
        cell: (workspace) => (
          <span className="text-muted-foreground block min-w-0 truncate text-xs">
            {workspace.access_label}
          </span>
        ),
      },
      {
        key: "files",
        header: t("files"),
        align: "right",
        sortable: true,
        // `null` rather than `0` for one nobody counted: an absence is not a small
        // number, and the table sorts it last either way.
        sortValue: (workspace) => workspace.file_count,
        cell: (workspace) => (
          <span className="text-muted-foreground text-xs">{workspace.file_count ?? "—"}</span>
        ),
      },
      {
        key: "size",
        header: t("size"),
        align: "right",
        sortable: true,
        // What the files come to, not what the row weighs: `bytes_total` is the
        // stored document's size and zero for a container, which is how a size
        // column ends up calling a container empty.
        sortValue: (workspace) => workspace.measured_bytes,
        cell: (workspace) => (
          <span
            className="text-muted-foreground text-xs"
            title={
              workspace.measured_bytes === null && workspace.backend !== "state"
                ? t("onTheHostUnmeasured")
                : undefined
            }
          >
            {workspace.measured_bytes === null ? "—" : formatBytes(workspace.measured_bytes)}
          </span>
        ),
      },
      {
        key: "lastUsed",
        header: t("lastUsed"),
        cell: (workspace) => (
          <span className="text-muted-foreground text-xs">{used(workspace.last_used_at, t)}</span>
        ),
      },
    ],
    [t],
  );

  return (
    <div className="space-y-4">
      <ListCard
        // The view, not the page's own title again. Under a page headed
        // `Workspaces` the card said `Workspaces` and then repeated the page's
        // two sentences - three lines of chrome saying one thing.
        title={flat ? t("everyFile") : t("byWorkspace")}
        // A count, which is what this line is for. It carried the page header's
        // own two sentences, so the same prose was on screen twice - once under
        // the title and once under the card's.
        counted={isLoading ? null : t("workspaceCount", { count: workspaces.length })}
        controls={
          /* Two questions, not two designs: "which workspaces exist" is a table
             of rows, and "who is holding a copy of that CSV" is a flat list of
             files. The second cannot be answered by opening the first one row at
             a time, which is what this exists for. */
          <div className="flex shrink-0 items-center gap-3">
            {!flat && (
              <label className="flex items-center gap-2 text-xs whitespace-nowrap">
                <Switch
                  checked={measure}
                  onCheckedChange={setMeasure}
                  aria-label={t("countFiles")}
                />
                <span className="text-muted-foreground" title={t("countFilesHint")}>
                  {t("countFiles")}
                </span>
              </label>
            )}
            <div className="flex gap-1">
              <Button
                variant={flat ? "ghost" : "secondary"}
                size="sm"
                aria-pressed={!flat}
                onClick={() => setFlat(false)}
              >
                {t("byWorkspace")}
              </Button>
              <Button
                variant={flat ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={flat}
                onClick={() => setFlat(true)}
              >
                {t("allFiles")}
              </Button>
            </div>
          </div>
        }
        contentClassName="p-0"
      >
        {flat ? (
          <FlatFiles />
        ) : (
          <>
            <DataTable<WorkspaceSummary>
              columns={columns}
              rows={workspaces}
              getRowKey={(workspace) => workspace.id}
              loading={isLoading}
              error={error}
              empty={t("noAgentKeepingFiles")}
              className="rounded-none border-0 bg-transparent"
            />
            {/* What counting left out, on screen rather than in a log. A host that
              did not answer leaves a row saying `—`, which is indistinguishable
              from a workspace holding nothing. */}
            {measure && (unreadable > 0 || truncated) && (
              <p className="text-muted-foreground border-border border-t px-5 py-2 text-xs">
                {unreadable > 0 && t("someHostsSilent", { count: unreadable })}
                {unreadable > 0 && truncated && " · "}
                {truncated && t("countingStopped")}
              </p>
            )}
          </>
        )}
      </ListCard>
    </div>
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
  const tc = useTranslations("common");
  const { listing, isLoading, error } = useAllWorkspaceFiles(true);
  const [opened, setOpened] = useState<FlatFile | null>(null);
  const [sort, setSort] = useState<FlatSort>("name");

  const sorted = useMemo(
    () => [...(listing?.items ?? [])].sort((a, b) => compareFlat(sort, a, b)),
    [listing, sort],
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
      <p className="text-muted-foreground px-5 py-8 text-center text-sm">
        {t("noAgentHoldingFile")}
      </p>
    );

  return (
    <div className="space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchFiles")} />
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
        <ul className="grid items-start gap-2 sm:grid-cols-2 lg:grid-cols-3">
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
              <p className="text-muted-foreground flex items-center gap-1 px-1 text-[11px]">
                <Link
                  href={ROUTES.WORKSPACE_DETAIL(file.workspace_id)}
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
