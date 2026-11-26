"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { ToolCall, TurnFileSource } from "@/types/chat";
import { useTurnFileSource } from "@/hooks/use-turn-file-source";
import { workspaceFileAccess } from "@/lib/workspace-files";
import { producedWorkspacePaths, workspaceLinkPath } from "@/lib/produced-workspace-files";
import { basename } from "@/lib/tool-steps";
import { FileViewer } from "@/components/files";

type FileLink = { open: (() => void) | null };
const FileLinks = createContext<((href: string) => FileLink | null) | null>(null);

/** An answer can open only this turn's successfully produced files at its recorded origin. */
export function TurnFileLinks({
  calls,
  fileSource,
  children,
}: {
  calls: readonly ToolCall[];
  fileSource?: TurnFileSource;
  children: ReactNode;
}) {
  const source = useTurnFileSource(fileSource);
  const sourceKey = JSON.stringify(source);
  const paths = useMemo(() => producedWorkspacePaths(calls), [calls]);
  const [opened, setOpened] = useState<{ path: string; sourceKey: string } | null>(null);
  const lookup = useCallback(
    (href: string): FileLink | null => {
      const canonical = workspaceLinkPath(href);
      const path = canonical ? paths.get(canonical) : undefined;
      if (!path) return null;
      return { open: source ? () => setOpened({ path, sourceKey }) : null };
    },
    [paths, source, sourceKey],
  );
  return (
    <FileLinks value={lookup}>
      {children}
      {opened && source && opened.sourceKey === sourceKey && (
        <FileViewer
          file={{ name: basename(opened.path), path: opened.path, size: null, modifiedAt: null }}
          access={workspaceFileAccess(source, opened.path)}
          onClose={() => setOpened(null)}
        />
      )}
    </FileLinks>
  );
}

/** Keep the link component mounted as streamed tool receipts update its provenance. */
export function TurnFileLink({
  href,
  label,
  title,
  children,
}: {
  href?: string;
  label: ReactNode;
  title?: string;
  children: ReactNode;
}) {
  const lookup = useContext(FileLinks);
  const file = href ? lookup?.(href) : null;
  if (!file) return children;
  if (!file.open) return <span>{label}</span>;
  return (
    <button
      type="button"
      title={title}
      className="text-foreground hover:text-brand-hover decoration-brand cursor-pointer font-medium underline decoration-2 underline-offset-[3px] transition-colors"
      onClick={file.open}
    >
      {label}
    </button>
  );
}
