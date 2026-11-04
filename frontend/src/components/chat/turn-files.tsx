"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileIcon, FileViewer } from "@/components/files";
import { useTurnFileSource } from "@/hooks/use-turn-file-source";
import { toolCallsOf } from "@/lib/chat-sources";
import { basename } from "@/lib/tool-steps";
import { filesChangedOf } from "@/lib/turn-extras";
import { workspaceFileAccess, type FileSource } from "@/lib/workspace-files";
import type { ChatMessage } from "@/types/chat";

/** Exact tool-reported paths, rather than file names guessed from the answer. */
export function TurnFiles({ message }: { message: ChatMessage }) {
  const source = useTurnFileSource(message.fileSource);
  const paths = filesChangedOf(toolCallsOf(message));
  if (message.role !== "assistant" || message.isStreaming || paths.length === 0 || !source)
    return null;
  return <FileLinks paths={paths} source={source} />;
}

function workspacePath(source: FileSource, path: string): string | null {
  if (source.kind !== "local") return path;
  const normalized = path.replaceAll("\\", "/");
  const root = source.root.replaceAll("\\", "/").replace(/\/$/, "");
  let relative = normalized;
  if (normalized.startsWith(root + "/")) relative = normalized.slice(root.length + 1);
  else if (normalized.startsWith("/") || /^[a-z]:/i.test(normalized)) return null;
  if (relative.split("/").includes("..")) return null;
  return relative;
}

function FileLinks({ paths, source }: { paths: string[]; source: FileSource }) {
  const t = useTranslations("chat.tools.codingAgent");
  const [reading, setReading] = useState<string | null>(null);
  const files = [
    ...new Set(
      paths.flatMap((path) => {
        const resolved = workspacePath(source, path);
        return resolved === null ? [] : [resolved];
      }),
    ),
  ];
  if (files.length === 0) return null;
  return (
    <div className="mt-2 space-y-2">
      <p className="text-muted-foreground text-xs">{t("filesChanged", { count: files.length })}</p>
      <div className="flex flex-wrap gap-2">
        {files.map((path) => (
          <button
            key={path}
            type="button"
            title={path}
            onClick={() => setReading(path)}
            className="border-foreground/10 hover:bg-accent flex max-w-full min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors"
          >
            <FileIcon name={path} className="text-muted-foreground size-4 shrink-0" />
            <span className="truncate">{path}</span>
          </button>
        ))}
      </div>
      {reading !== null && (
        <FileViewer
          key={reading}
          file={{ name: basename(reading), path: reading }}
          access={workspaceFileAccess(source, reading)}
          onClose={() => setReading(null)}
          navigation={{
            names: files,
            index: files.indexOf(reading),
            onSelect: (index) => {
              const path = files[index];
              if (path) setReading(path);
            },
          }}
        />
      )}
    </div>
  );
}
