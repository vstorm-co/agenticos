"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, X } from "lucide-react";

import { FileContent, FileIcon } from "@/components/files";
import { useFileActions } from "@/hooks";
import { useFilePreviewStore } from "@/stores";
import { attachmentAccess } from "@/lib/file-api";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

const DEFAULT_WIDTH = 480;
const MIN_WIDTH = 320;
const MAX_WIDTH = 1100;
const STORAGE_KEY = "filePreviewPanelWidth";

/**
 * Right-hand sidebar that previews the attachment selected in the chat.
 *
 * A panel rather than a dialog, and that is the whole of why this is not
 * `FileViewer`: an attachment is read *beside* the message that carries it, and the
 * user drags its left edge to whatever width the file needs. What it shows is the
 * shared `FileContent`, so an attachment and a file the agent wrote render
 * identically - this used to be a fourth implementation with its own kind table, its
 * own icon set and its own copy of every viewer.
 */
export function FilePreviewPanel() {
  const t = useTranslations("chat");
  const file = useFilePreviewStore((s) => s.file);
  const close = useFilePreviewStore((s) => s.close);

  // The stored width is read once, as the initial state, rather than written
  // back from an effect - which rendered the panel at the default first and
  // snapped it to the remembered width a frame later. Safe to read during
  // render because the panel renders nothing until a file is selected, and
  // nothing selects one on the server: there is no first paint to disagree with.
  const [width, setWidth] = useState<number>(storedWidth);
  const [isDragging, setIsDragging] = useState(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      // Width = distance from cursor to right edge of viewport.
      const next = clamp(window.innerWidth - e.clientX, MIN_WIDTH, MAX_WIDTH);
      setWidth(next);
    };
    const onUp = () => {
      setIsDragging(false);
      try {
        localStorage.setItem(STORAGE_KEY, String(width));
      } catch {
        /* private mode / quota - drop persistence silently */
      }
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isDragging, width]);

  if (!file) return null;

  return (
    <aside
      className="border-foreground/10 bg-card relative flex h-full max-w-full shrink-0 flex-col border-l"
      style={{ width: `${width}px` }}
      aria-label={t("filePreview")}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("resizeFilePreview")}
        onMouseDown={onMouseDown}
        className={cn(
          "group absolute top-0 left-0 z-20 h-full w-1.5 -translate-x-1/2 cursor-col-resize",
          isDragging && "bg-foreground/20",
        )}
      >
        <div className="bg-foreground/0 group-hover:bg-foreground/15 absolute top-1/2 left-1/2 h-12 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors" />
      </div>

      <PanelBody file={file} onClose={close} />
    </aside>
  );
}

/**
 * The header and the file, split out so the resizing above owns no file state.
 *
 * Keyed on the file's id by the caller, which is what makes `useFileActions` and the
 * queries under `FileContent` start clean when the selection changes rather than
 * carrying the previous attachment's failure into the next one's header.
 */
function PanelBody({
  file,
  onClose,
}: {
  file: { id: string; filename: string; mime_type?: string };
  onClose: () => void;
}) {
  const t = useTranslations("chat");
  const tf = useTranslations("files");
  const access = useMemo(() => attachmentAccess(file), [file]);
  const { download, openInNewTab, error } = useFileActions(access);
  const kind = resolveFileKind(file.filename, file.mime_type);
  const suffix = suffixOf(file.filename);

  return (
    <>
      <header className="border-foreground/10 flex items-center gap-2 border-b px-3 py-2">
        <span className="bg-foreground/8 text-foreground/65 flex h-7 w-7 shrink-0 items-center justify-center rounded-md">
          <FileIcon name={file.filename} mimeType={file.mime_type} className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-sm font-medium" title={file.filename}>
            {file.filename}
          </p>
          <p className="text-foreground/50 truncate font-mono text-[10px] tracking-wider uppercase">
            {suffix === "" ? (file.mime_type ?? tf(`kinds.${kind}`)) : suffix}
          </p>
        </div>
        <button
          type="button"
          onClick={openInNewTab}
          className="text-foreground/55 hover:bg-foreground/5 hover:text-foreground inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          title={t("openNewTab")}
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={download}
          className="text-foreground/55 hover:bg-foreground/5 hover:text-foreground inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          title={t("download2")}
        >
          <Download className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={onClose}
          className="text-foreground/55 hover:bg-foreground/5 hover:text-foreground inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          aria-label={t("closePreview")}
          title={t("close")}
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {error !== null && <p className="text-destructive px-3 py-2 text-xs">{error}</p>}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        <FileContent access={access} kind={kind} name={file.filename} />
      </div>
    </>
  );
}

function storedWidth(): number {
  /* v8 ignore next -- an SSR guard, and the test environment is jsdom */
  if (typeof window === "undefined") return DEFAULT_WIDTH;
  const n = parseInt(localStorage.getItem(STORAGE_KEY) ?? "", 10);
  return Number.isFinite(n) ? clamp(n, MIN_WIDTH, MAX_WIDTH) : DEFAULT_WIDTH;
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}
