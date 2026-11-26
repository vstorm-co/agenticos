"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, Download } from "lucide-react";
import { FileContent, FileIcon, type ViewerFile } from "@/components/files";
import { FileCarousel, type ViewerNavigation } from "@/components/files/file-viewer";
import { IconButton } from "@/components/ui";
import { MarkdownModeToggle } from "@/components/ui/markdown-mode-toggle";
import { useFileActions } from "@/hooks";
import type { FileAccess } from "@/lib/file-access";
import { hasSourceView, resolveFileKind } from "@/lib/file-kinds";
import { formatBytes, timeAgo } from "@/lib/utils";

/** The shared file renderer, kept mounted while another workspace tab is selected. */
export function WorkspaceFilePreview({
  file,
  access,
  onBack,
  navigation,
}: {
  file: ViewerFile;
  access: FileAccess;
  onBack: () => void;
  navigation?: ViewerNavigation;
}) {
  const t = useTranslations("files");
  const workspace = useTranslations("chat.workspace");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [mode, setMode] = useState<"source" | "preview">("preview");
  const { download, error } = useFileActions(access);
  const kind = resolveFileKind(file.name, file.mimeType);
  const modified = file.modifiedAt ? timeAgo(file.modifiedAt, tTime, locale) : "";
  const strip = navigation && navigation.names.length > 1 ? navigation : null;
  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      onKeyDown={(event) => {
        if (!strip) return;
        const target = event.target;
        if (
          !(target instanceof Element) ||
          target.closest('input, textarea, [contenteditable], [role="tablist"]')
        )
          return;
        if (event.key === "ArrowLeft" && strip.index > 0) strip.onSelect(strip.index - 1);
        if (event.key === "ArrowRight" && strip.index < strip.names.length - 1)
          strip.onSelect(strip.index + 1);
      }}
    >
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b p-3">
        <IconButton
          aria-label={workspace("allFiles")}
          title={workspace("allFiles")}
          onClick={onBack}
        >
          <ArrowLeft />
        </IconButton>
        <FileIcon
          name={file.name}
          mimeType={file.mimeType}
          className="text-muted-foreground size-4 shrink-0"
        />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-medium" title={file.path ?? file.name}>
            {file.name}
          </h2>
          {(file.size != null || modified !== "") && (
            <p className="text-muted-foreground text-xs">
              {file.size != null && formatBytes(file.size)}
              {file.size != null && modified !== "" && " · "}
              {modified !== "" && t("modified", { when: modified })}
            </p>
          )}
        </div>
        {hasSourceView(kind) && <MarkdownModeToggle mode={mode} onChange={setMode} />}
        <IconButton aria-label={t("download")} title={t("download")} onClick={download}>
          <Download />
        </IconButton>
      </header>
      {error !== null && (
        <p role="alert" className="text-destructive shrink-0 px-3 py-2 text-xs">
          {error}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <FileContent
          access={access}
          kind={kind}
          name={file.name}
          asSource={mode === "source"}
          bare
        />
      </div>
      {strip && <FileCarousel strip={strip} />}
    </div>
  );
}
