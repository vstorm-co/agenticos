"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { Download, FolderOpen } from "lucide-react";
import { toast } from "sonner";
import { WorkspaceReadNotice } from "./workspace-read-notice";
import { ChatSidePanel, ChatPanelHeader } from "./chat-side-panel";

import { FileCard, FileViewer, FileIcon, PathTree } from "@/components/files";
import { useConversationWorkspace } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useLocalWorkspace } from "@/hooks/use-desktop";
import { useFilePreviewStore } from "@/stores";
import { useChatPanelStore } from "@/stores/chat-panel-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { getFileUrl } from "@/lib/file-api";
import { cn, formatBytes } from "@/lib/utils";
import { isRenderSafeImage } from "@/lib/file-kinds";
import { treeOf, type WorkspaceTreeNode } from "@/lib/workspace-tree";
import { suffixOf, resolveFileKind } from "@/lib/file-kinds";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import {
  downloadConversationFolder,
  workspaceFileAccess,
  type FileSource,
} from "@/lib/workspace-files";
import type { ConversationFile } from "@/lib/conversation-workspace-api";
import type { ChatMessageFile } from "@/types";

interface WorkspaceFilesProps {
  beforeFirstMessage?: boolean;
  conversationId: string | null;
  /** Bumped when a turn ends, because a turn is what changes the files. */
  revision: number;
  /**
   * What people attached to this conversation, newest last.
   *
   * Listed beside what the agent wrote because "Files" in a chat means the files in
   * that chat, and somebody who has just dragged in a CSV looks for it here. Passed
   * in rather than fetched: the messages already carry their attachments, both live
   * and after a reload, so a request would be asking for what is on screen.
   *
   * They are also *not* the same thing as the workspace's `/uploads` copy. An agent
   * with a workspace gets one written there and can open it; an agent without one
   * gets nothing, and before this the panel had nothing to show either.
   */
  attachments: ChatMessageFile[];
  /** Where the closed panel's button is drawn - among the composer's controls. */
  buttonSlot: HTMLElement | null;
  /**
   * Lie over the conversation rather than beside it - in a narrow window (the
   * Architect's, the test panel), where a column of its own squeezed the
   * composer until its buttons fell out of it.
   */
  overlay?: boolean;
}

/**
 * What the agent is keeping in this conversation, behind a button.
 *
 * **Closed by default, and that is the change.** A permanent third column took
 * space from the transcript in every conversation, including the ones where the
 * agent keeps nothing — so closed it is one icon among the composer's controls,
 * and the count on that icon is what says there is something to open. A strip
 * of its own down the right edge cost the conversation a margin for one button.
 *
 * `owner_label` is shown and is not decoration. Under `agent` scope one workspace is
 * shared by everybody who talks to that agent, so somebody opens a chat and finds a
 * file they never created — and without a line saying whose files these are, the
 * reasonable reading is that something leaked.
 *
 * A file opens into the shared viewer rather than into a `<pre>` under its own row.
 * A 288-pixel column can list what the agent is keeping; it cannot show a report, a
 * chart or a PDF, and the panel used to answer "open this" with the first 60
 * characters of a line.
 */
export function WorkspaceFiles({
  conversationId,
  revision,
  attachments,
  buttonSlot,
  overlay = false,
  beforeFirstMessage = false,
}: WorkspaceFilesProps) {
  const t = useTranslations("chat.files");
  const controls = useTranslations("chat.controls");
  // A chat working on this computer keeps its files in the folder there, which
  // only the desktop app can list (#2305); everywhere else it is the server's.
  const shell = useShell();
  const target = useWorkOnStore((state) => state.targetFor(conversationId));
  const localRoot =
    isDesktopShell(shell) && target !== null && !target.computer_grant ? target.folder : null;
  const cloud = useConversationWorkspace(
    !beforeFirstMessage && localRoot === null ? conversationId : null,
  );
  const local = useLocalWorkspace(
    beforeFirstMessage ? null : localRoot,
    t("onThisComputer", { folder: localRoot?.split(/[\\/]/).filter(Boolean).at(-1) ?? "" }),
  );
  const { workspace, error, refresh } = localRoot === null ? cloud : local;
  const openAttachment = useFilePreviewStore((state) => state.open);
  const [open, setOpen] = useState(false);
  const sourcesOpen = useSourcesPanelStore((state) => state.isOpen);
  const closeSources = useSourcesPanelStore((state) => state.close);
  const visible = open && !sourcesOpen && !beforeFirstMessage;
  useEffect(() => {
    if (overlay) return;
    useChatPanelStore.getState().setFilesOpen(visible);
    return () => useChatPanelStore.getState().setFilesOpen(false);
  }, [visible, overlay]);
  const panelId = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const closePanel = useCallback(() => setOpen(false), []);
  const [reading, setReading] = useState<ConversationFile | null>(null);
  if (useChanged(conversationId)) {
    setOpen(false);
    setReading(null);
  }
  // The chat addresses files through its conversation, not through the workspace's
  // id: that route authorises by fetching the conversation, so somebody this chat
  // was shared with reaches the same files.
  const source = useMemo<FileSource | null>(() => {
    if (localRoot !== null) return { kind: "local", root: localRoot };
    return conversationId === null ? null : { kind: "conversation", id: conversationId };
  }, [conversationId, localRoot]);

  // Re-read when a turn ends rather than on a timer: the chat knows exactly when
  // the files could have changed, and a poll is wrong almost every time it fires.
  // In an effect and not during render - a refetch is a side effect, and React is
  // entitled to render this twice.
  useEffect(() => {
    void refresh();
  }, [revision, refresh]);

  // Keep the trigger stable while the workspace is created or a turn parks.
  // The main chat disables it before its first message; embedded chats keep
  // their existing access to pre-run uploads.
  const files = workspace?.items.filter((file) => !file.is_dir) ?? [];

  // An attachment an agent *with* a workspace already holds is one file, not
  // two. `workspace_path` on the server names it from the first eight hex of the
  // file's id, so matching on that is exact rather than a guess about names - a
  // name match would collide the moment two people attach `report.csv`, which is
  // the case the id prefix exists to keep apart.
  //
  // Matched on the *last segment* rather than on a directory prefix: a listing
  // spells a path as the backend spells it - `./uploads/x` from a shell, `x`
  // from a glob, `/uploads/x` from a stored workspace - and a match anchored on
  // one of those showed the same file twice under the others (#1039).
  //
  // Every segment rather than only the last: an archive is unpacked into a folder
  // named the same way, `uploads/<eight hex>-repo/...`, so the folder is the copy.
  const stored = new Set(
    (workspace?.items ?? []).flatMap((file) => file.path.split("/").filter(Boolean)),
  );
  const unstored = attachments.filter((file) => {
    const prefix = file.id.replaceAll("-", "").slice(0, 8);
    return ![...stored].some((name) => name.startsWith(`${prefix}-`));
  });
  const count = files.length + unstored.length;
  // Folders count here, where they do not in `count`: the tree draws an empty folder too.
  const empty = (workspace?.items.length ?? 0) === 0 && unstored.length === 0;
  const readIssue = error ?? workspace?.unreadable_reason ?? null;

  // Only for the server's workspace: the archive route is the conversation's, and a
  // folder on this computer is already a folder on this computer. Wherever the tree
  // is drawn, folders included: the server zips an empty folder as that folder.
  const tErrors = useTranslations("errors");
  const zipFolder =
    source?.kind === "conversation" && (workspace?.items.length ?? 0) > 0
      ? (folder: string) =>
          void downloadConversationFolder(source.id, folder).catch((err: unknown) =>
            // The server's refusal - a folder too large, one gone - says why in
            // its own words; anything else is the browser's, in English.
            toast.error(err instanceof ApiError ? getErrorMessage(err, tErrors) : t("zipFailed")),
          )
      : null;

  return (
    <>
      {buttonSlot &&
        createPortal(
          <button
            ref={toggle}
            type="button"
            disabled={beforeFirstMessage}
            aria-label={
              visible ? t("title") : count === 0 ? t("show") : t("showWithCount", { count })
            }
            aria-controls={panelId}
            aria-expanded={visible}
            title={
              beforeFirstMessage
                ? controls("afterFirstMessage")
                : visible
                  ? t("close")
                  : count === 0
                    ? t("show")
                    : t("showWithCount", { count })
            }
            onClick={() => {
              if (sourcesOpen) {
                closeSources();
                setOpen(true);
              } else setOpen((current) => !current);
            }}
            className={cn(
              "text-muted-foreground hover:text-foreground hover:bg-accent/60 relative inline-flex size-8 items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-35",
              visible && "bg-foreground/[0.06] text-foreground",
            )}
          >
            <FolderOpen className="size-4" aria-hidden />
            {count > 0 && (
              <span className="bg-foreground text-background absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px]">
                {count}
              </span>
            )}
          </button>,
          buttonSlot,
        )}
      {visible && (
        <ChatSidePanel
          label={t("title")}
          sizing="sources"
          panelId={panelId}
          contained={overlay}
          onClose={closePanel}
        >
          {({ fullscreen, toggleFullscreen }) => (
            <>
              <ChatPanelHeader
                title={t("title")}
                icon={<FolderOpen className="size-4" />}
                closeLabel={t("close")}
                onClose={closePanel}
                contained={overlay}
                fullscreen={fullscreen}
                toggleFullscreen={toggleFullscreen}
                actions={
                  zipFolder && (
                    <button
                      type="button"
                      title={t("downloadAll")}
                      aria-label={t("downloadAll")}
                      onClick={() => zipFolder("")}
                      className="text-muted-foreground hover:bg-muted hover:text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
                    >
                      <Download className="size-4" aria-hidden />
                    </button>
                  )
                }
                subtitle={
                  workspace !== null && workspace.backend !== "none" ? (
                    <>
                      {workspace.owner_label}
                      {workspace.backend === "state" && workspace.bytes_total > 0 && (
                        <> · {t("storedSuffix", { size: formatBytes(workspace.bytes_total) })}</>
                      )}
                    </>
                  ) : undefined
                }
              />
              <div className="min-h-0 flex-1 scrollbar-thin space-y-4 overflow-y-auto overscroll-contain p-4">
                {conversationId === null && (
                  <p className="text-muted-foreground text-xs">{t("beforeStart")}</p>
                )}

                {readIssue !== null && (
                  <WorkspaceReadNotice
                    detail={readIssue}
                    code={error === null ? workspace?.unreadable_code : undefined}
                    onRetry={refresh}
                    cloud={localRoot === null}
                    failed={error !== null}
                  />
                )}

                {/* Two different answers, and they were one. "Nothing yet" is right for a
          workspace that is empty; for an agent that has none it describes a wait
          that will never end, since no turn is going to put a file there. */}
                {workspace !== null && workspace.unreadable_reason == null && empty && (
                  <p className="text-muted-foreground text-xs">
                    {workspace.backend === "none" ? t("noWorkspace") : t("empty")}
                  </p>
                )}

                {/* Full-width chips leave room for names in this narrow panel. */}
                {(workspace?.items.length ?? 0) > 0 && (
                  <WorkspaceTree
                    files={workspace?.items ?? []}
                    selectedPath={reading?.path ?? null}
                    onOpen={setReading}
                    onZipFolder={zipFolder}
                  />
                )}

                {/* What people attached and the agent has no copy of. Its own group, under its
          own heading, because where a file came from changes what it means: the agent
          wrote the ones above and can read them back, while these are only in the
          chat - so an agent with no workspace can be *shown* one and cannot open it.
          Opened through the shared preview panel, which is what the attachment chips
          on the messages already use, rather than the workspace viewer that would
          have nothing to read. */}
                {unstored.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-muted-foreground text-xs font-medium">{t("attached")}</p>
                    <ul className="space-y-2">
                      {unstored.map((file) => (
                        <li key={file.id}>
                          <FileCard
                            compact
                            name={file.filename}
                            mimeType={file.mime_type}
                            // An attachment is behind the same authenticated address the
                            // viewer reads it from, so the card can draw the picture rather
                            // than a grey glyph standing in for one. Nothing is fetched here
                            // - the browser loads what an `img` points at, and a chat holds
                            // a handful of attachments rather than a listing. Only a
                            // render-safe type: a TIFF is an `image` kind no browser draws, so
                            // it gets its glyph rather than a broken thumbnail (#1591).
                            imageUrl={
                              isRenderSafeImage(file.mime_type) ? getFileUrl(file.id) : null
                            }
                            onOpen={() => openAttachment(file)}
                            className="w-full"
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {source !== null && reading !== null && (
                  <FileViewer
                    file={{
                      name: reading.path.split("/").filter(Boolean).pop() ?? reading.path,
                      path: reading.path,
                      size: reading.size,
                      modifiedAt: reading.modified_at,
                    }}
                    access={workspaceFileAccess(source, reading.path)}
                    onClose={() => setReading(null)}
                  />
                )}
              </div>
            </>
          )}
        </ChatSidePanel>
      )}
    </>
  );
}

function WorkspaceTree({
  files,
  selectedPath,
  onOpen,
  onZipFolder,
}: {
  files: ConversationFile[];
  selectedPath: string | null;
  onOpen: (file: ConversationFile) => void;
  /** Download one folder as a `.zip`, where the workspace has a route for it. */
  onZipFolder: ((path: string) => void) | null;
}) {
  const t = useTranslations("chat.files");
  const tFiles = useTranslations("files");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const nodes = treeOf(files);
  const open = new Set<string>();
  const visit = (items: WorkspaceTreeNode<ConversationFile>[]) => {
    for (const node of items)
      if (node.isDir) {
        if (!collapsed.has(node.path)) open.add(node.path);
        visit(node.children);
      }
  };
  visit(nodes);
  return (
    <PathTree
      nodes={nodes}
      label={t("title")}
      selectedPath={selectedPath}
      openPaths={open}
      onToggleFolder={(path) =>
        setCollapsed((previous) => {
          const next = new Set(previous);
          if (next.has(path)) next.delete(path);
          else next.add(path);
          return next;
        })
      }
      onSelect={(node) => {
        if (node.file) onOpen(node.file);
      }}
      renderFolderMeta={
        onZipFolder
          ? (node) => (
              <button
                type="button"
                aria-label={t("downloadFolder", { name: node.label })}
                title={t("downloadFolder", { name: node.label })}
                onClick={() => onZipFolder(node.path)}
                className="text-muted-foreground hover:text-foreground hover:bg-foreground/5 touch:size-11 mr-1 flex size-7 shrink-0 items-center justify-center rounded-md focus-visible:outline-offset-[-2px]"
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
              </button>
            )
          : undefined
      }
      renderFile={(node) => (
        <>
          <FileIcon name={node.label} className="text-muted-foreground size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium">{node.label}</span>
            <span className="text-muted-foreground block text-[11px]">
              {[
                suffixOf(node.label).toUpperCase() ||
                  tFiles(`kinds.${resolveFileKind(node.label)}`),
                node.file?.size == null ? null : formatBytes(node.file.size),
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </span>
        </>
      )}
    />
  );
}
