"use client";

import { useState, type ReactNode } from "react";
import { Download, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { FileContent } from "./file-content";
import { FileIcon } from "./file-icon";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useFileActions } from "@/hooks";
import type { FileAccess } from "@/lib/file-access";
import { hasSourceView, resolveFileKind, suffixOf, type FileKind } from "@/lib/file-kinds";
import { cn, formatBytes, timeAgo } from "@/lib/utils";

/** What is known about a file before anything is fetched. */
export interface ViewerFile {
  /** What it is called. The header leads with this. */
  name: string;
  /**
   * Where it sits, shown only when it says more than the name does.
   *
   * The header used to print this unconditionally, which for a file at a workspace
   * root meant the name twice - once as the title and once in monospace underneath.
   */
  path?: string | null;
  /** What the origin says it is, where it knows. A name is only a suggestion. */
  mimeType?: string | null;
  size?: number | null;
  /** ISO 8601. Absent where the origin does not record one. */
  modifiedAt?: string | null;
}

/** One more thing to read this file as, which only its own surface knows about. */
export interface ViewerTab {
  value: string;
  label: string;
  content: ReactNode;
}

interface FileViewerProps {
  file: ViewerFile;
  /** How to reach the bytes. The viewer never learns which of the four origins it is. */
  access: FileAccess;
  /**
   * Views belonging to the surface rather than to the file.
   *
   * A knowledge base document's *parsed* text is the example and the reason this
   * exists: what the ingestion pipeline extracted, beside what a human sees, is the
   * comparison that dialog is for - and it is ingestion, which nothing else here
   * knows or should learn about.
   */
  extraTabs?: ViewerTab[];
  onClose: () => void;
}

/**
 * One file, opened.
 *
 * A dialog and not an expanding row: a report, a chart or a PDF is the thing somebody
 * wants to look at, and a preview squeezed into a 288-pixel side panel or a third of
 * a grid cell is a preview of nothing. Every surface that opens a file opens this, so
 * a file means the same thing wherever it was clicked - which is the whole of #136.
 * There were four of these, and the one people hit most often, from the chat panel,
 * was the poorest: it could show text and offer a download, and everything else - a
 * PDF, an image, a CSV, an HTML page an agent wrote - was a byte count.
 *
 * **Sized to the content, with a floor.** A three-byte file used to open the same
 * 900-pixel box as a report. The body has a small minimum and grows to 70% of the
 * viewport; the width is the only thing the kind decides, because a PDF read in a
 * column as wide as a paragraph is a PDF nobody can read.
 */
export function FileViewer({ file, access, extraTabs = [], onClose }: FileViewerProps) {
  const t = useTranslations("files");
  const kind = resolveFileKind(file.name, file.mimeType);
  const { download, openInNewTab, error } = useFileActions(access);
  const [view, setView] = useState("preview");

  const tabs: ViewerTab[] = [
    { value: "preview", label: t("preview"), content: null },
    ...(hasSourceView(kind) ? [{ value: "source", label: t("source"), content: null }] : []),
    ...extraTabs,
  ];
  const extra = extraTabs.find((tab) => tab.value === view);

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className={cn(
          "max-h-[90vh] gap-3 overflow-hidden p-4 sm:p-6",
          isWide(kind) ? "sm:max-w-5xl" : "sm:max-w-3xl",
        )}
      >
        <DialogHeader className="gap-1 pr-8">
          <DialogTitle className="flex min-w-0 items-center gap-2 text-base">
            <FileIcon
              name={file.name}
              mimeType={file.mimeType}
              className="text-muted-foreground h-4 w-4 shrink-0"
            />
            <span className="truncate">{file.name}</span>
          </DialogTitle>
          {/* What it is, how big, and when it changed - which is what the second line
              of a file header is for. It used to be the path, and for a file at a
              workspace root the path is the name. */}
          <DialogDescription className="text-xs">{describe(file, kind, t)}</DialogDescription>
          {showsPath(file.path) && (
            <p className="text-muted-foreground truncate font-mono text-xs">{file.path}</p>
          )}
        </DialogHeader>

        <div
          className={cn(
            "flex flex-wrap items-center gap-2",
            tabs.length > 1 ? "justify-between" : "justify-end",
          )}
        >
          {tabs.length > 1 && (
            <Tabs value={view} onValueChange={setView}>
              <TabsList>
                {tabs.map((tab) => (
                  <TabsTrigger key={tab.value} value={tab.value}>
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={openInNewTab} title={t("openInNewTab")}>
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
            <Button variant="outline" size="sm" onClick={download}>
              <Download className="h-3.5 w-3.5" />
              {t("download")}
            </Button>
          </div>
        </div>

        {error !== null && <p className="text-destructive text-xs">{error}</p>}

        <div className="max-h-[70vh] min-h-16 min-w-0 overflow-auto">
          {extra !== undefined ? (
            extra.content
          ) : (
            <FileContent
              access={access}
              kind={kind}
              name={file.name}
              asSource={view === "source"}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Whether the path is worth a line of its own.
 *
 * It is not when the file is at the root: `/report.csv` beside a title reading
 * `report.csv` is the name twice, differing by a slash. It is when there are folders
 * in it, because a workspace holds `out/report.csv` beside `report.csv` often enough
 * that the name alone is ambiguous.
 */
function showsPath(path: string | null | undefined): boolean {
  return path != null && path.split("/").filter(Boolean).length > 1;
}

/**
 * The file in one line: what kind, how big, when it changed.
 *
 * Built as parts and joined rather than written as a sentence with holes in it, since
 * every one of the three is missing on some surface - a workspace listing carries no
 * modification time at all, and a directory entry carries no size.
 */
function describe(
  file: ViewerFile,
  kind: FileKind,
  t: (key: string, values?: Record<string, string>) => string,
): string {
  const suffix = suffixOf(file.name);
  const parts = [suffix === "" ? t(`kinds.${kind}`) : suffix.toUpperCase()];
  if (file.size != null) parts.push(formatBytes(file.size));
  if (file.modifiedAt != null) {
    const when = timeAgo(file.modifiedAt);
    if (when !== "") parts.push(t("modified", { when }));
  }
  return parts.join(" · ");
}

/**
 * Whether this needs the wide dialog.
 *
 * The kinds a browser renders as a *document* rather than as text: a PDF in a
 * three-column-wide box is two words a line, and an image or a video scaled into one
 * is a thumbnail. Everything else reads better narrow.
 */
function isWide(kind: FileKind): boolean {
  return kind === "pdf" || kind === "image" || kind === "video" || kind === "csv";
}
