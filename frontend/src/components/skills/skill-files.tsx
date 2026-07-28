"use client";

/**
 * The pieces a skill's file view is made of: the tree, the pane that reads one
 * file, and the two ways to add more.
 *
 * They live apart from the editor that arranges them because the arrangement is
 * the thing that changed — the body and the files were two stacked panels with
 * a footer between them, and they are one skill. See `SkillWorkbench`.
 *
 * Names are paths and always were, so the tree is derived rather than stored:
 * a folder is a prefix some file has, which makes an empty one impossible. That
 * is the honest model, because the agent asks for a file by name and can never
 * ask for a folder.
 */

import { useState } from "react";
import {
  ChevronRight,
  Code2,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  Trash2,
  Upload,
} from "lucide-react";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button, Input, Label, Textarea } from "@/components/ui";
import { useSkillResource } from "@/hooks";
import { previewKind, type Preview, type TreeNode } from "@/lib/file-tree";
import { cn } from "@/lib/utils";
import type { SkillResourceSummary } from "@/types/providers";

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
            // A folder is never the selection — only a file opens in the pane —
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
 * One file: what it says, and what it is.
 *
 * Rendered by default and editable behind a toggle, because these are read far
 * more often than they are written — and a Markdown reference read as raw
 * asterisks is the thing this pane exists to stop.
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
  const { resource: loaded, isLoading } = useSkillResource(skillId, resource.id);
  const [draft, setDraft] = useState<string | null>(null);

  const value = draft ?? loaded?.content ?? "";
  const dirty = draft !== null && draft !== loaded?.content;

  return (
    <FileViewer
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
              Save file
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                Discard
              </Button>
            )}
          </>
        ) : null
      }
    />
  );
}

/**
 * A named piece of text, read or edited, filling whatever it is given.
 *
 * Presentational on purpose: the skill's own body is one of these and is not
 * fetched, so the thing that reads a file and the thing that renders one had to
 * come apart. It is also what lets `SKILL.md` have the preview toggle every
 * other Markdown file here has — it is Markdown, and reading it as raw
 * asterisks was the odd one out.
 */
export function FileViewer({
  name,
  content,
  loading,
  canEdit,
  onChange,
  onDelete,
  footer,
  header,
}: {
  name: string;
  content: string;
  loading?: boolean;
  canEdit: boolean;
  onChange: (next: string) => void;
  onDelete?: () => void;
  footer?: React.ReactNode;
  /** Anything the owner wants above the content — the body's own fields. */
  header?: React.ReactNode;
}) {
  const [mode, setMode] = useState<"preview" | "source">("preview");

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-md border">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{name}</span>
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          <ModeButton
            icon={Eye}
            label="Preview"
            active={mode === "preview"}
            onClick={() => setMode("preview")}
          />
          <ModeButton
            icon={Code2}
            label="Source"
            active={mode === "source"}
            onClick={() => setMode("source")}
          />
        </div>
        {onDelete && canEdit && (
          <Button variant="ghost" size="icon" aria-label={`Remove ${name}`} onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {header && <div className="space-y-1.5 border-b px-3 py-2">{header}</div>}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {loading ? (
          <p className="text-muted-foreground text-xs">Loading…</p>
        ) : mode === "source" ? (
          // Fills the pane rather than sitting in it: a fixed-row box inside a
          // tall panel leaves the text in a letterbox with dead space under it.
          <Textarea
            value={content}
            onChange={(event) => onChange(event.target.value)}
            readOnly={!canEdit}
            className="h-full min-h-[16rem] resize-none font-mono text-xs"
            aria-label={`${name} source`}
          />
        ) : (
          <FilePreview kind={previewKind(name)} name={name} content={content} />
        )}
      </div>

      {footer && <div className="flex items-center gap-2 border-t px-3 py-2">{footer}</div>}
    </div>
  );
}

/** What a file looks like when it is not being edited. */
function FilePreview({ kind, name, content }: { kind: Preview; name: string; content: string }) {
  if (content.trim() === "") {
    return <p className="text-muted-foreground text-xs">This file is empty.</p>;
  }

  if (kind === "markdown") return <MarkdownContent content={content} />;

  if (kind === "html") {
    // Sandboxed with no allowances: this is somebody's uploaded file, rendered
    // to be looked at. Scripts, forms and same-origin access are all things it
    // has no reason to need and every reason not to get.
    return (
      <iframe
        title={`${name} preview`}
        srcDoc={content}
        sandbox=""
        className="bg-background h-96 w-full rounded border"
      />
    );
  }

  // The Markdown renderer highlights fenced code, so a code file is fenced with
  // its own extension as the language rather than growing a second highlighter.
  if (kind === "code") {
    const language = name.split(".").pop()?.toLowerCase() ?? "";
    return <MarkdownContent content={`\`\`\`${language}\n${content}\n\`\`\``} />;
  }

  return <pre className="text-foreground/90 font-mono text-xs whitespace-pre-wrap">{content}</pre>;
}

function ModeButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof Eye;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
        active ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
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
  onPick: (files: FileList | null) => void;
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
        // Not in React's JSX types — it is a real attribute every browser that
        // matters implements, and it is the only way to pick a folder.
        {...(directory ? ({ webkitdirectory: "" } as Record<string, string>) : {})}
        className="hidden"
        onChange={(event) => {
          onPick(event.target.files);
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
          <Label htmlFor="resource-name">Path</Label>
          <Input
            id="resource-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="references/workflows.md"
            spellCheck={false}
            className="font-mono text-sm"
            required
          />
          <p className="text-muted-foreground text-xs">
            A folder is made by naming a file inside it — there is nothing else to create.
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="resource-description">Description</Label>
          <Input
            id="resource-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What is in it, so the model can decide without loading it"
          />
        </div>
      </div>
      <Textarea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        rows={10}
        placeholder="The file body"
        aria-label="File contents"
        className="font-mono text-xs"
      />
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={busy || name.trim() === ""}>
          Add file
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Bytes as a reader scans them — kilobytes are the interesting unit here. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
}
