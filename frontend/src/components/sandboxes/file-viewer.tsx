"use client";

import { useState } from "react";
import { Download } from "lucide-react";

import { FilePreview } from "./file-preview";
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
import { useFileDownload } from "@/hooks";
import { cn } from "@/lib/utils";
import { isMarkdown, type FileSource } from "@/lib/workspace-files";

interface WorkspaceFileViewerProps {
  source: FileSource;
  /** The file to show. It is mounted when one is open and not before. */
  path: string;
  onClose: () => void;
}

/**
 * One workspace file, opened.
 *
 * A dialog and not an expanding row, which is what both surfaces had: a report, a
 * chart or a PDF is the thing somebody wants to look at, and a preview squeezed into
 * a 288-pixel side panel or a third of a grid cell is a preview of nothing. The chat
 * panel and the Workspaces browser open the same component, so a file means the same
 * thing wherever it was clicked.
 *
 * Preview *and* source for markdown, the same pair a skill's files already offer and
 * for the same reason: both are the file. An agent writing a report means the prose,
 * an agent writing a prompt or a spec means the characters it will be read back as -
 * and a `#` that silently became large type is how somebody fails to notice their
 * agent is writing markdown into a file nothing reads as markdown. Download is always
 * offered, including for what cannot be shown at all.
 */
export function WorkspaceFileViewer({ source, path, onClose }: WorkspaceFileViewerProps) {
  const [view, setView] = useState<"preview" | "source">("preview");
  const { download, error } = useFileDownload(source);
  const name = path.split("/").filter(Boolean).pop() ?? path;

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] gap-3 overflow-hidden sm:max-w-3xl">
        <DialogHeader className="pr-8">
          <DialogTitle className="truncate">{name}</DialogTitle>
          {/* The whole path, because a workspace holds `out/report.csv` beside
              `report.csv` often enough that the name alone is ambiguous. */}
          <DialogDescription className="truncate font-mono text-xs">{path}</DialogDescription>
        </DialogHeader>

        {/* The toggle only exists for markdown, so without it the download sits on
            the right on its own rather than beside an empty slot. */}
        <div
          className={cn(
            "flex items-center gap-2",
            isMarkdown(path) ? "justify-between" : "justify-end",
          )}
        >
          {isMarkdown(path) && (
            <Tabs value={view} onValueChange={(next) => setView(next as "preview" | "source")}>
              <TabsList>
                <TabsTrigger value="preview">Preview</TabsTrigger>
                <TabsTrigger value="source">Source</TabsTrigger>
              </TabsList>
            </Tabs>
          )}
          <Button variant="outline" size="sm" onClick={() => download(path)}>
            <Download className="h-3.5 w-3.5" />
            Download
          </Button>
        </div>

        {error !== null && <p className="text-destructive text-xs">{error}</p>}

        <div className="min-h-0 overflow-auto">
          <FilePreview source={source} path={path} asSource={view === "source"} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
