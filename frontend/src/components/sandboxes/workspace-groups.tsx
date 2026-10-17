"use client";

import Link from "next/link";
import { ArrowRight, Folder } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { DocumentTile } from "@/components/sandboxes/document-tile";
import { Card } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { FlatFile } from "@/lib/sandbox-workspaces-api";

/** Tiles a group shows before it says how many more its folder holds. */
const SHOWN = 8;

/** One workspace's files: what sits at its top, and the folders under it. */
export interface WorkspaceGroup {
  workspaceId: string;
  agent: { id: string; slug: string; name: string; hasAvatar: boolean };
  accessLabel: string;
  /** The conversation it belongs to, which tells two of one agent's workspaces apart. */
  conversationTitle: string | null;
  /** Files at the top of the workspace, in the order the list was sorted. */
  files: FlatFile[];
  /** Top-level folders: how many files are anywhere inside, and the first few names. */
  folders: { name: string; count: number; sample: string[] }[];
  total: number;
}

/** File names a folder tile lists, so it says what is in it before it is opened. */
const SAMPLE = 3;

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
 * folders as one tile each.
 */
export function groupByWorkspace(files: readonly FlatFile[]): WorkspaceGroup[] {
  const byWorkspace = new Map<string, FlatFile[]>();
  for (const file of files) {
    const held = byWorkspace.get(file.workspace_id) ?? [];
    held.push(file);
    byWorkspace.set(file.workspace_id, held);
  }
  return [...byWorkspace.values()]
    .sort((a, b) => newest(b) - newest(a))
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
        files: top,
        folders: [...folders.entries()]
          .map(([name, folder]) => ({ name, ...folder }))
          .sort((a, b) => a.name.localeCompare(b.name)),
        total: held.length,
      };
    });
}

export function WorkspaceGroups({
  groups,
  onOpen,
  onDownload,
}: {
  groups: WorkspaceGroup[];
  onOpen: (file: FlatFile) => void;
  onDownload: (file: FlatFile) => void;
}) {
  const t = useTranslations("sandboxes");
  return (
    <div className="rise-in space-y-6">
      {groups.map((group) => {
        const folder = ROUTES.DOCUMENT_FOLDER(group.workspaceId);
        const folders = group.folders.slice(0, SHOWN);
        const files = group.files.slice(0, Math.max(0, SHOWN - folders.length));
        const hidden = group.folders.length - folders.length + group.files.length - files.length;
        return (
          <section key={group.workspaceId} aria-label={group.agent.name} className="space-y-2.5">
            <header className="flex min-w-0 items-center gap-2.5">
              <AgentAvatar
                agentId={group.agent.id}
                slug={group.agent.slug}
                hasAvatar={group.agent.hasAvatar}
                size="sm"
                className="h-6 w-6"
              />
              <span className="text-foreground shrink-0 text-sm font-medium">
                {group.agent.name}
              </span>
              {/* The conversation where there is one: an agent with three chats
                  has three workspaces, and its name alone told them apart from
                  nothing. The scope otherwise. */}
              <span className="text-muted-foreground min-w-0 truncate text-xs">
                {group.conversationTitle ?? group.accessLabel} ·{" "}
                {t("fileCount", { count: group.total })}
              </span>
              <Link
                href={folder}
                className="text-muted-foreground hover:text-foreground ml-auto flex shrink-0 items-center gap-1 text-xs font-medium"
              >
                {t("workspaces.openFolder")}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            </header>
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {folders.map((entry) => (
                <li key={entry.name}>
                  <Link href={folder} className="group block h-full">
                    <Card className="group-hover:border-foreground/20 flex h-full flex-col gap-3 p-4">
                      <span className="flex min-w-0 items-center gap-3">
                        <span className="bg-muted grid h-10 w-10 shrink-0 place-items-center rounded-lg">
                          <Folder className="text-muted-foreground h-5 w-5" aria-hidden />
                        </span>
                        <span className="min-w-0">
                          <span className="text-foreground block truncate text-sm font-medium">
                            {entry.name}
                          </span>
                          <span className="text-muted-foreground text-xs">
                            {t("fileCount", { count: entry.count })}
                          </span>
                        </span>
                      </span>
                      <ul className="text-muted-foreground space-y-1 font-mono text-[11px]">
                        {entry.sample.map((name) => (
                          <li key={name} className="truncate">
                            {name}
                          </li>
                        ))}
                      </ul>
                    </Card>
                  </Link>
                </li>
              ))}
              {files.map((file) => (
                <li key={file.path}>
                  <DocumentTile
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
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
              >
                {t("workspaces.moreInFolder", { count: hidden })}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            )}
          </section>
        );
      })}
    </div>
  );
}
