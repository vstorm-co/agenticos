"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Download, Folder } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { FileIcon } from "@/components/files";
import { Button, Card } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import type { FlatFile } from "@/lib/sandbox-workspaces-api";
import { formatBytes, timeAgo } from "@/lib/utils";
import { documentName } from "@/lib/workspace-files";

/** Rows a group shows before it says how many more its folder holds. */
const SHOWN = 8;

/** File names a folder row lists, so it says what is in it before it is opened. */
const SAMPLE = 3;

/** One workspace's files: what sits at its top, and the folders under it. */
export interface WorkspaceGroup {
  workspaceId: string;
  agent: { id: string; slug: string; name: string; hasAvatar: boolean };
  accessLabel: string;
  /** The conversation it belongs to, which tells two of one agent's workspaces apart. */
  conversationTitle: string | null;
  /** That conversation, when it is the reader's own to open; null otherwise. */
  conversationId: string | null;
  /** Files at the top of the workspace, in the order the list was sorted. */
  files: FlatFile[];
  /** Top-level folders: how many files are anywhere inside, and the first few names. */
  folders: { name: string; count: number; sample: string[] }[];
  total: number;
  /** When anything in it last changed, as a timestamp; 0 when nothing says. */
  changed: number;
}

/** A path as the workspace's own: no leading slash, no `/workspace/` prefix. */
function relative(path: string): string {
  return path.replace(/^\/+/, "").replace(/^workspace\//, "");
}

function newest(files: readonly FlatFile[]): number {
  return Math.max(
    0,
    ...files.map((file) => (file.modified_at === null ? 0 : new Date(file.modified_at).getTime())),
  );
}

/**
 * The files grouped by the workspace that holds them, most recently changed first.
 *
 * A coding agent's project is a tree - `app/`, `tests/`, a README - and four of
 * them listed file by file, sorted by name, put five `.gitignore`s side by side.
 * Grouped, each workspace reads as the project it is: its loose files, and its
 * folders as one row each.
 */
export function groupByWorkspace(files: readonly FlatFile[]): WorkspaceGroup[] {
  const byWorkspace = new Map<string, FlatFile[]>();
  for (const file of files) {
    const held = byWorkspace.get(file.workspace_id) ?? [];
    held.push(file);
    byWorkspace.set(file.workspace_id, held);
  }
  return [...byWorkspace.values()]
    .map((held) => {
      const first = held[0]!;
      const folders = new Map<string, { count: number; sample: string[] }>();
      const top: FlatFile[] = [];
      for (const file of held) {
        const [head, ...rest] = relative(file.path).split("/");
        // An attachment sits in `uploads/` by the platform's filing, not because
        // anybody made a folder: it is what the person gave, shown as a file.
        if (rest.length === 0 || file.from_upload) {
          top.push(file);
          continue;
        }
        const folder = folders.get(head!) ?? { count: 0, sample: [] };
        folder.count += 1;
        if (folder.sample.length < SAMPLE) folder.sample.push(rest.at(-1)!);
        folders.set(head!, folder);
      }
      return {
        workspaceId: first.workspace_id,
        agent: {
          id: first.agent_id,
          slug: first.agent_slug,
          name: first.agent_name,
          hasAvatar: first.agent_has_avatar,
        },
        accessLabel: first.access_label,
        conversationTitle: first.conversation_title ?? null,
        conversationId: first.conversation_id ?? null,
        files: top,
        folders: [...folders.entries()]
          .map(([name, folder]) => ({ name, ...folder }))
          .sort((a, b) => a.name.localeCompare(b.name)),
        total: held.length,
        changed: newest(held),
      };
    })
    .sort((a, b) => b.changed - a.changed);
}

/**
 * Every workspace as a card of its own: the conversation it belongs to, then
 * its folders and files as compact rows.
 *
 * Rows rather than preview tiles because a project is read by its names - `app`,
 * `tests`, `README.md` - and a tile per file spent a row of the screen on one
 * HTML icon. The previews are what the page's Recent strip is for.
 */
export function WorkspaceGroups({
  groups,
  onOpen,
  onDownload,
}: {
  groups: WorkspaceGroup[];
  onOpen: (file: FlatFile) => void;
  onDownload: (file: FlatFile) => void;
}) {
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <GroupCard key={group.workspaceId} group={group} onOpen={onOpen} onDownload={onDownload} />
      ))}
    </div>
  );
}

function GroupCard({
  group,
  onOpen,
  onDownload,
}: {
  group: WorkspaceGroup;
  onOpen: (file: FlatFile) => void;
  onDownload: (file: FlatFile) => void;
}) {
  const t = useTranslations("sandboxes");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const folder = ROUTES.DOCUMENT_FOLDER(group.workspaceId);
  const folders = group.folders.slice(0, SHOWN);
  const files = group.files.slice(0, Math.max(0, SHOWN - folders.length));
  const hidden = group.folders.length - folders.length + group.files.length - files.length;
  const title = group.conversationTitle ?? group.agent.name;
  const meta = [
    group.conversationTitle === null ? group.accessLabel : group.agent.name,
    t("fileCount", { count: group.total }),
    group.changed === 0 ? null : timeAgo(new Date(group.changed).toISOString(), tTime, locale),
  ].filter(Boolean);

  return (
    <section aria-label={title}>
      <Card className="overflow-hidden">
        <header className="flex min-w-0 items-center gap-3 px-4 pt-4 pb-3">
          <AgentAvatar
            agentId={group.agent.id}
            slug={group.agent.slug}
            hasAvatar={group.agent.hasAvatar}
            size="sm"
            className="h-8 w-8"
          />
          <div className="min-w-0 flex-1">
            {group.conversationId !== null ? (
              <Link
                href={`${ROUTES.CHAT}?id=${group.conversationId}`}
                className="text-foreground block truncate text-sm font-medium hover:underline"
              >
                {title}
              </Link>
            ) : (
              <p className="text-foreground truncate text-sm font-medium">{title}</p>
            )}
            <p className="text-muted-foreground truncate text-xs">{meta.join(" · ")}</p>
          </div>
          <Button asChild variant="ghost" size="sm" className="shrink-0">
            <Link href={folder}>
              {/* The arrow alone on a phone, where the words took the title's room. */}
              <span className="max-sm:sr-only">{t("workspaces.openFolder")}</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </Button>
        </header>
        <ul className="grid grid-cols-1 gap-1 px-2 pb-2 sm:grid-cols-2">
          {folders.map((entry) => (
            <li key={entry.name}>
              <Link
                href={folder}
                className="hover:bg-accent/60 flex min-w-0 items-center gap-3 rounded-lg px-2 py-2"
              >
                <span className="bg-muted grid h-9 w-9 shrink-0 place-items-center rounded-lg">
                  <Folder className="text-muted-foreground h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="text-foreground block truncate text-sm font-medium">
                    {entry.name}
                  </span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {t("fileCount", { count: entry.count })} · {entry.sample.join(", ")}
                  </span>
                </span>
              </Link>
            </li>
          ))}
          {files.map((file) => (
            <li key={file.path}>
              <FileRow
                file={file}
                onOpen={() => onOpen(file)}
                onDownload={() => onDownload(file)}
              />
            </li>
          ))}
        </ul>
        {hidden > 0 && (
          <Link
            href={folder}
            className="text-muted-foreground hover:text-foreground border-border/60 flex items-center gap-1 border-t px-4 py-2.5 text-xs"
          >
            {t("workspaces.moreInFolder", { count: hidden })}
            <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        )}
      </Card>
    </section>
  );
}

/** One file as a row: what kind, its name as the person knows it, and a download. */
function FileRow({
  file,
  onOpen,
  onDownload,
}: {
  file: FlatFile;
  onOpen: () => void;
  onDownload: () => void;
}) {
  const t = useTranslations("sandboxes");
  const tc = useTranslations("common");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const name = documentName(file.path, file.from_upload);
  const thumbnail = resolveFileKind(file.path) === "image" ? file.thumbnail : null;
  const meta = [
    suffixOf(file.path).toUpperCase(),
    file.size === null ? null : formatBytes(file.size),
    file.modified_at === null ? null : timeAgo(file.modified_at, tTime, locale),
    file.from_upload ? t("workspaces.fromMe") : null,
  ].filter(Boolean);

  return (
    <div className="group/row hover:bg-accent/60 flex min-w-0 items-center gap-3 rounded-lg px-2 py-2">
      <button
        type="button"
        onClick={onOpen}
        aria-label={tc("openNamed", { name })}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <span className="bg-muted relative grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-lg">
          {thumbnail !== null ? (
            <Image src={thumbnail} alt="" fill className="object-cover" unoptimized />
          ) : (
            <FileIcon name={file.path} className="text-muted-foreground h-4 w-4" />
          )}
        </span>
        <span className="min-w-0">
          <span title={file.path} className="text-foreground block truncate text-sm font-medium">
            {name}
          </span>
          <span className="text-muted-foreground block truncate text-xs">{meta.join(" · ")}</span>
        </span>
      </button>
      <Button
        variant="ghost"
        size="icon"
        aria-label={tc("downloadNamed", { name })}
        onClick={onDownload}
        className="text-muted-foreground touch:opacity-100 h-8 w-8 shrink-0 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100"
      >
        <Download className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
