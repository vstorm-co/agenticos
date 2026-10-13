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

import { useMemo, useState } from "react";
import { FileText, Upload } from "lucide-react";

import { FileEditor, PathTree, type PathTreeNode } from "@/components/files";
import { Button, Input, Label, Textarea } from "@/components/ui";
import { useSkillResource } from "@/hooks";
import { folderPaths, type TreeNode } from "@/lib/file-tree";
import type { SkillResourceSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

/**
 * A skill's files as a tree, over the shared one.
 *
 * The mechanics - the recursion, the expand-collapse set, the chevron, the two
 * folder icons, `role="tree"` - are `PathTree` in `components/files`, shared with
 * the workspace explorer, which had written all of it a second time with a
 * second node shape (#137). What is left here is what a *skill's* row says and
 * how this surface identifies a file: by resource id, because two files can
 * share a name in different folders and the id is what the pane fetches by.
 *
 * Folders start open, which is what `folderPaths` answers: a skill holds a
 * handful of files and a tree that starts closed hides all of them.
 */
export function FileTree({
  nodes,
  openId,
  onOpen,
}: {
  nodes: TreeNode[];
  openId: string | null;
  onOpen: (id: string) => void;
}) {
  const t = useTranslations("skills");
  // What is *collapsed*, rather than what is open. Every folder starts open - a
  // skill holds a handful of files - and derived this way a folder added or
  // uploaded after a collapse is open too, where a snapshot of open paths would
  // leave it shut.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const rows = useMemo(() => asPathNodes(nodes), [nodes]);
  const openPaths = useMemo(
    () => new Set(folderPaths(nodes).filter((path) => !collapsed.has(path))),
    [nodes, collapsed],
  );
  const selectedPath = useMemo(() => pathOfId(rows, openId), [rows, openId]);

  return (
    <PathTree
      nodes={rows}
      label={t("fileTree")}
      selectedPath={selectedPath}
      onSelect={(node) => {
        if (node.id !== null) onOpen(node.id);
      }}
      openPaths={openPaths}
      onToggleFolder={(path) =>
        setCollapsed((previous) => {
          const next = new Set(previous);
          if (!next.delete(path)) next.add(path);
          return next;
        })
      }
      renderFile={(node) => (
        <>
          <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate font-mono text-xs">{node.label}</span>
        </>
      )}
    />
  );
}

/** A skill's tree node, plus the id this surface opens a file by. */
interface SkillTreeNode extends PathTreeNode {
  id: string | null;
  children: SkillTreeNode[];
}

/** `lib/file-tree`'s union in the shape the shared tree reads. */
function asPathNodes(nodes: TreeNode[]): SkillTreeNode[] {
  return nodes.map((node) =>
    node.kind === "folder"
      ? {
          label: node.label,
          path: node.path,
          isDir: true,
          children: asPathNodes(node.children),
          id: null,
        }
      : { label: node.label, path: node.path, isDir: false, children: [], id: node.id },
  );
}

/** The path of the file with this id, which is what the shared tree selects by. */
function pathOfId(nodes: SkillTreeNode[], id: string | null): string | null {
  if (id === null) return null;
  for (const node of nodes) {
    if (!node.isDir) {
      if (node.id === id) return node.path;
      continue;
    }
    const found = pathOfId(node.children, id);
    if (found !== null) return found;
  }
  return null;
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
