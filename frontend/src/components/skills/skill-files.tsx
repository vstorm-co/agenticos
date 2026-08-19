"use client";

/**
 * The pieces a skill's file view is made of: the tree, what fetches one file
 * into the shared editor, and the two ways to add more.
 *
 * They live apart from the editor that arranges them because the arrangement is
 * the thing that changed - the body and the files were two stacked panels with
 * a footer between them, and they are one skill. See `SkillWorkbench`. The pane
 * itself is `FileEditor` in `components/files`: a named draft, rendered by
 * default and editable behind a toggle, is not a skills idea.
 *
 * Names are paths and always were, so the tree is derived rather than stored:
 * a folder is a prefix some file has, which makes an empty one impossible. That
 * is the honest model, because the agent asks for a file by name and can never
 * ask for a folder.
 */

import { useState } from "react";
import { ChevronRight, FileText, Folder, FolderOpen, Upload } from "lucide-react";

import { FileEditor } from "@/components/files";
import { Button, Input, Label, Textarea } from "@/components/ui";
import { useSkillResource } from "@/hooks";
import type { TreeNode } from "@/lib/file-tree";
import { cn } from "@/lib/utils";
import type { SkillResourceSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

/** The tree itself, so a caller can put its own things above it. */
export function FileTree({
  nodes,
  openId,
  onOpen,
}: {
  nodes: TreeNode[];
  openId: string | null;
  onOpen: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleFolder = (path: string) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  if (nodes.length === 0) return null;
  return (
    <TreeLevel
      nodes={nodes}
      depth={0}
      openId={openId}
      collapsed={collapsed}
      onToggleFolder={toggleFolder}
      onOpen={onOpen}
    />
  );
}

function TreeLevel({
  nodes,
  depth,
  openId,
  collapsed,
  onToggleFolder,
  onOpen,
}: {
  nodes: TreeNode[];
  depth: number;
  openId: string | null;
  collapsed: Set<string>;
  onToggleFolder: (path: string) => void;
  onOpen: (id: string) => void;
}) {
  return (
    <ul role={depth === 0 ? "tree" : "group"} className="space-y-0.5">
      {nodes.map((node) =>
        node.kind === "folder" ? (
          <li
            key={node.path}
            role="treeitem"
            aria-expanded={!collapsed.has(node.path)}
            // A folder is never the selection - only a file opens in the pane -
            // but the role requires the attribute, and saying "false" is the
            // truthful way to say it.
            aria-selected={false}
          >
            <button
              type="button"
              onClick={() => onToggleFolder(node.path)}
              style={{ paddingLeft: `${depth * 12 + 4}px` }}
              className="hover:bg-accent flex w-full items-center gap-1.5 rounded px-1 py-1 text-left text-sm transition-colors"
            >
              <ChevronRight
                className={cn(
                  "text-muted-foreground h-3 w-3 shrink-0 transition-transform",
                  !collapsed.has(node.path) && "rotate-90",
                )}
              />
              {collapsed.has(node.path) ? (
                <Folder className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              ) : (
                <FolderOpen className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              )}
              <span className="truncate">{node.label}</span>
            </button>
            {!collapsed.has(node.path) && (
              <TreeLevel
                nodes={node.children}
                depth={depth + 1}
                openId={openId}
                collapsed={collapsed}
                onToggleFolder={onToggleFolder}
                onOpen={onOpen}
              />
            )}
          </li>
        ) : (
          <li key={node.id} role="treeitem" aria-selected={openId === node.id}>
            <button
              type="button"
              onClick={() => onOpen(node.id)}
              style={{ paddingLeft: `${depth * 12 + 20}px` }}
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-1 py-1 text-left text-sm transition-colors",
                openId === node.id ? "bg-accent text-foreground" : "hover:bg-accent/60",
              )}
            >
              <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              <span className="truncate font-mono text-xs">{node.label}</span>
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

/**
 * One of a skill's files, fetched and handed to the shared editor.
 *
 * The draft is held here rather than in the pane, so Save and Discard know
 * whether anything was typed. A resource's content is not in the listing, which
 * is why this exists at all and the skill's own body does not need it.
 */
export function FilePane({
  skillId,
  resource,
  canEdit,
  busy,
  onSave,
  onDelete,
}: {
  skillId: string;
  resource: SkillResourceSummary;
  canEdit: boolean;
  busy: boolean;
  onSave: (content: string) => void;
  onDelete: () => void;
}) {
  const t = useTranslations("skills");
  const { resource: loaded, isLoading } = useSkillResource(skillId, resource.id);
  const [draft, setDraft] = useState<string | null>(null);

  const value = draft ?? loaded?.content ?? "";
  const dirty = draft !== null && draft !== loaded?.content;

  return (
    <FileEditor
      name={resource.name}
      content={value}
      loading={isLoading || loaded === undefined}
      canEdit={canEdit}
      onChange={setDraft}
      onDelete={onDelete}
      footer={
        canEdit ? (
          <>
            <Button
              size="sm"
              disabled={!dirty || busy}
              onClick={() => {
                onSave(value);
                setDraft(null);
              }}
            >
              {t("saveFile")}
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                {t("discard2")}
              </Button>
            )}
          </>
        ) : null
      }
    />
  );
}

export function UploadButton({
  icon: Icon = Upload,
  label,
  directory,
  onPick,
}: {
  icon?: typeof Upload;
  label: string;
  directory?: boolean;
  /** Always a list, never a `FileList | null` - the conversion happens once, here. */
  onPick: (files: File[]) => void;
}) {
  return (
    // Shaped like the Button beside it rather than approximately like it: a
    // file input cannot be a <button>, so the label carries the same classes.
    <label className="border-input hover:bg-accent inline-flex h-8 cursor-pointer items-center justify-center gap-1.5 rounded-md border px-2 text-sm font-medium transition-colors">
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {label}
      <input
        type="file"
        multiple
        // Not in React's JSX types - it is a real attribute every browser that
        // matters implements, and it is the only way to pick a folder.
        {...(directory ? ({ webkitdirectory: "" } as Record<string, string>) : {})}
        className="hidden"
        onChange={(event) => {
          onPick(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
    </label>
  );
}

export function NewFileForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (draft: { name: string; description: string | null; content: string }) => void;
}) {
  const t = useTranslations("skills");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");

  return (
    <form
      className="space-y-3 rounded-md border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ name: name.trim(), description: description.trim() || null, content });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="resource-name">{t("path")}</Label>
          <Input
            id="resource-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="references/workflows.md"
            spellCheck={false}
            className="font-mono text-sm"
            required
          />
          <p className="text-muted-foreground text-xs">{t("folderMadeByNaming")}</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="resource-description">{t("description2")}</Label>
          <Input
            id="resource-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("whatSoModelCan")}
          />
        </div>
      </div>
      <Textarea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        rows={10}
        placeholder={t("fileBody")}
        aria-label={t("fileContents")}
        className="font-mono text-xs"
      />
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={busy || name.trim() === ""}>
          {t("addFile")}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t("cancel2")}
        </Button>
      </div>
    </form>
  );
}

/** Bytes as a reader scans them - kilobytes are the interesting unit here. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
}
