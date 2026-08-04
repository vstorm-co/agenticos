"use client";

import { useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Download, ExternalLink, FileText, Loader2, ScanText, X } from "lucide-react";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button } from "@/components/ui/button";
import { DialogOverlay, DialogPortal } from "@/components/ui/dialog";
import { apiClient } from "@/lib/api-client";
import { getParsedKBDocument } from "@/lib/rag-api";
import { cn } from "@/lib/utils";
import type { KBParsedContent } from "@/types";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

// ─────────────────────────────────────────────────────────────────────────────
// Viewer type detection
// ─────────────────────────────────────────────────────────────────────────────

type ViewerKind = "pdf" | "image" | "markdown" | "text" | "video" | "audio" | "html" | "unknown";

const TEXT_EXTENSIONS = new Set([
  "txt",
  "log",
  "csv",
  "tsv",
  "py",
  "js",
  "ts",
  "jsx",
  "tsx",
  "mjs",
  "cjs",
  "json",
  "jsonl",
  "yaml",
  "yml",
  "toml",
  "ini",
  "env",
  "cfg",
  "sh",
  "bash",
  "zsh",
  "fish",
  "sql",
  "xml",
  "html",
  "htm",
  "css",
  "scss",
  "sass",
  "less",
  "rs",
  "go",
  "java",
  "cpp",
  "cc",
  "c",
  "h",
  "cs",
  "rb",
  "php",
  "swift",
  "kt",
  "scala",
  "r",
  "m",
  "lua",
  "ex",
  "exs",
]);

function resolveViewerKind(mimeType: string, filename: string): ViewerKind {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";

  if (mimeType === "application/pdf") return "pdf";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("video/")) return "video";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType === "text/html" || ext === "html" || ext === "htm") return "html";
  if (ext === "md" || ext === "markdown" || mimeType === "text/markdown") return "markdown";
  if (
    mimeType.startsWith("text/") ||
    mimeType === "application/json" ||
    mimeType === "application/javascript" ||
    mimeType === "application/xml" ||
    mimeType === "application/x-yaml" ||
    TEXT_EXTENSIONS.has(ext)
  )
    return "text";

  return "unknown";
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

interface FileViewerDoc {
  id: string;
  filename: string;
  filetype: string | null;
}

interface FileViewerProps {
  kbId: string;
  doc: FileViewerDoc | null;
  open: boolean;
  onClose: () => void;
}

export function FileViewer({ kbId, doc, open, onClose }: FileViewerProps) {
  const t = useTranslations("kb");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [viewerKind, setViewerKind] = useState<ViewerKind>("unknown");
  const [mimeType, setMimeType] = useState("application/octet-stream");
  const blobUrlRef = useRef<string | null>(null);

  // The other half of the comparison this dialog exists for: the original
  // bytes above, and here what the parser made of them. Fetched lazily on the
  // first switch to the tab, then kept - a stored parse does not change.
  const [tab, setTab] = useState<"original" | "parsed">("original");
  const [parsed, setParsed] = useState<KBParsedContent | null>(null);
  const [parsedLoading, setParsedLoading] = useState(false);
  const [parsedError, setParsedError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
    };
  }, []);

  // Cleared during render, revoked in the effect below. The two halves are
  // different things: emptying the panel is state, and releasing the object URL
  // is a side effect on the browser. Doing the first in an effect meant the
  // previous document's bytes were rendered once more before it closed.
  if (useChanged(`${open}|${doc?.id ?? ""}`) && (!open || !doc)) {
    setBlobUrl(null);
    setTextContent(null);
    setError(null);
    setLoading(false);
    setTab("original");
    setParsed(null);
    setParsedError(null);
    setParsedLoading(false);
  }

  useEffect(() => {
    if (!open || !doc) {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
      return;
    }

    let cancelled = false;
    const currentDoc = doc;

    (async () => {
      setLoading(true);
      setError(null);
      setBlobUrl(null);
      setTextContent(null);

      try {
        // `raw` rather than `fetch`: org-scoped endpoint, and without the
        // organization header the backend answers from the personal one.
        const res = await apiClient.raw(`/kb/${kbId}/documents/${currentDoc.id}/download`);
        if (cancelled) return;

        const ct = res.headers.get("content-type") || "application/octet-stream";
        const mime = (ct.split(";")[0] ?? ct).trim();
        const kind = resolveViewerKind(mime, currentDoc.filename);

        if (!cancelled) {
          setMimeType(mime);
          setViewerKind(kind);
        }

        if (kind === "text" || kind === "markdown") {
          const text = await res.text();
          if (!cancelled) setTextContent(text);
        } else {
          const blob = await res.blob();
          if (!cancelled) {
            if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
            const url = URL.createObjectURL(blob);
            blobUrlRef.current = url;
            setBlobUrl(url);
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : t("failedLoadFile"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, doc?.id, kbId]);

  useEffect(() => {
    if (!open || !doc || tab !== "parsed" || parsed !== null || parsedError !== null) return;

    let cancelled = false;
    const currentDoc = doc;

    (async () => {
      setParsedLoading(true);
      try {
        const data = await getParsedKBDocument(kbId, currentDoc.id);
        if (!cancelled) setParsed(data);
      } catch (e) {
        if (!cancelled) {
          setParsedError(e instanceof Error ? e.message : t("failedLoadParsedContent"));
        }
      } finally {
        if (!cancelled) setParsedLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, doc, tab, parsed, parsedError, kbId]);

  // ── Action helpers ──────────────────────────────────────────────────────────

  const makeTempUrl = (): string | null => {
    if (blobUrl) return null;
    if (textContent !== null)
      return URL.createObjectURL(new Blob([textContent], { type: mimeType }));
    return null;
  };

  const handleDownload = () => {
    if (!doc) return;
    const tempUrl = makeTempUrl();
    const url = blobUrl || tempUrl;
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    if (tempUrl) setTimeout(() => URL.revokeObjectURL(tempUrl), 0);
  };

  const handleOpenExternal = () => {
    const tempUrl = makeTempUrl();
    const url = blobUrl || tempUrl;
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
    if (tempUrl) setTimeout(() => URL.revokeObjectURL(tempUrl), 60_000);
  };

  // ── Rendering ───────────────────────────────────────────────────────────────

  const hasContent = blobUrl !== null || textContent !== null;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content className="bg-background data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 fixed top-[50%] left-[50%] z-50 flex h-[90vh] w-[95vw] max-w-5xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden border shadow-lg duration-200 sm:rounded-lg">
          {/* Header */}
          <div className="flex shrink-0 items-center gap-3 border-b px-4 py-2.5">
            <FileText className="text-muted-foreground h-4 w-4 shrink-0" />
            <DialogPrimitive.Title className="text-foreground flex-1 truncate text-sm font-medium">
              {doc?.filename ?? ""}
            </DialogPrimitive.Title>
            {/* Original vs parsed is the comparison this dialog is for, so the
                switch lives in the header rather than behind a menu. */}
            <div className="bg-muted flex shrink-0 items-center gap-0.5 rounded-lg p-0.5">
              {(["original", "parsed"] as const).map((choice) => (
                <button
                  key={choice}
                  type="button"
                  aria-pressed={tab === choice}
                  onClick={() => setTab(choice)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    tab === choice
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {choice === "original" ? t("original") : t("parsed")}
                </button>
              ))}
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              {hasContent && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground h-7 w-7 p-0"
                    onClick={handleOpenExternal}
                    title={t("openNewBrowserTab")}
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground h-7 w-7 p-0"
                    onClick={handleDownload}
                    title={t("downloadFile")}
                  >
                    <Download className="h-3.5 w-3.5" />
                  </Button>
                </>
              )}
              <DialogPrimitive.Close asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-foreground h-7 w-7 p-0"
                  title={t("close")}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </DialogPrimitive.Close>
            </div>
          </div>

          {/* Body */}
          <div className="relative min-h-0 flex-1 overflow-hidden">
            {tab === "parsed" && (
              <ParsedView parsed={parsed} loading={parsedLoading} error={parsedError} />
            )}

            {tab === "original" && loading && (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
              </div>
            )}

            {tab === "original" && !loading && error && (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
                <p className="text-destructive text-sm">{error}</p>
              </div>
            )}

            {tab === "original" && !loading && !error && viewerKind === "pdf" && blobUrl && (
              <iframe src={blobUrl} className="h-full w-full border-0" title={doc?.filename} />
            )}

            {tab === "original" && !loading && !error && viewerKind === "image" && blobUrl && (
              <div className="flex h-full items-center justify-center overflow-auto p-4">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={blobUrl}
                  alt={doc?.filename}
                  className="max-h-full max-w-full rounded object-contain"
                />
              </div>
            )}

            {tab === "original" && !loading && !error && viewerKind === "html" && blobUrl && (
              <iframe
                src={blobUrl}
                className="h-full w-full border-0"
                sandbox="allow-scripts allow-same-origin"
                title={doc?.filename}
              />
            )}

            {tab === "original" && !loading && !error && viewerKind === "video" && blobUrl && (
              <div className="flex h-full items-center justify-center p-4">
                {}
                <video src={blobUrl} controls className="max-h-full max-w-full rounded" />
              </div>
            )}

            {tab === "original" && !loading && !error && viewerKind === "audio" && blobUrl && (
              <div className="flex h-full items-center justify-center p-4">
                {}
                <audio src={blobUrl} controls className="w-full max-w-md" />
              </div>
            )}

            {tab === "original" &&
              !loading &&
              !error &&
              viewerKind === "markdown" &&
              textContent !== null && (
                <div className="h-full overflow-auto p-6">
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <MarkdownContent content={textContent} />
                  </div>
                </div>
              )}

            {tab === "original" &&
              !loading &&
              !error &&
              viewerKind === "text" &&
              textContent !== null && (
                <div className="h-full overflow-auto">
                  <pre className="text-foreground p-4 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
                    {textContent}
                  </pre>
                </div>
              )}

            {tab === "original" && !loading && !error && viewerKind === "unknown" && blobUrl && (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
                <p className="text-muted-foreground text-sm">{t("fileTypeCannotBe")}</p>
                <p className="text-muted-foreground text-xs">{doc?.filetype || mimeType}</p>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={handleOpenExternal}>
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                    {t("openBrowser")}
                  </Button>
                  <Button size="sm" onClick={handleDownload}>
                    <Download className="mr-1.5 h-3.5 w-3.5" />
                    {t("download")}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </DialogPrimitive.Root>
  );
}

/**
 * The reconstructed markdown a document parsed into, page by page.
 *
 * Chunks render separately with hairline dividers rather than joined, because
 * that is what was actually indexed: adjacent chunks repeat their configured
 * overlap, and a silent join would present the duplication as a parse bug.
 *
 * `has_text` comes from the server, which knows that an unreadable scan comes
 * back as an empty fenced block - not whitespace - and must not be shown as a
 * document that parsed fine.
 */
function ParsedView({
  parsed,
  loading,
  error,
}: {
  parsed: KBParsedContent | null;
  loading: boolean;
  error: string | null;
}) {
  const t = useTranslations("kb");
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    // Most often "No parsed content for this document": still processing, or
    // ingestion failed. A refusal to show a parse is not a broken screen.
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <p className="text-foreground text-sm font-medium">{t("noParsedContentShow")}</p>
        <p className="text-muted-foreground max-w-md text-xs">{error}</p>
      </div>
    );
  }

  if (!parsed) return null;

  if (!parsed.has_text) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
        <span className="bg-muted text-muted-foreground inline-flex h-12 w-12 items-center justify-center rounded-xl">
          <ScanText className="h-5 w-5" />
        </span>
        <div>
          <p className="text-foreground text-sm font-medium">{t("nothingReadableCameOut")}</p>
          <p className="text-muted-foreground mx-auto mt-1 max-w-md text-xs">
            {parsed.chunk_count > 0 ? t("everyPageCameBack") : t("nothingIndexedDocumentIts")}
          </p>
          {parsed.parser && (
            <p className="text-muted-foreground mt-2 font-mono text-xs">
              parsed with {parsed.parser}
            </p>
          )}
        </div>
      </div>
    );
  }

  const multiPage = parsed.pages.length > 1 || (parsed.pages[0]?.page_num ?? 1) !== 1;

  return (
    <div className="h-full overflow-auto">
      <div className="text-muted-foreground border-border bg-card sticky top-0 z-10 border-b px-6 py-2 text-xs">
        {t("whatWasIndexed", { count: parsed.chunk_count })}
        {parsed.parser && (
          <>
            {" "}
            · parsed with <span className="font-mono">{parsed.parser}</span>
          </>
        )}
        {parsed.chunk_count > 1 &&
          " · adjacent chunks repeat their overlap, so boundary text appears twice"}
      </div>
      <div className="space-y-6 p-6">
        {parsed.pages.map((page) => (
          <section key={page.page_num}>
            {multiPage && (
              <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
                Page {page.page_num}
              </p>
            )}
            {!page.has_text && (
              <p className="text-muted-foreground border-border mb-2 rounded-lg border border-dashed px-3 py-2 text-xs">
                {t("pageParsedNothingReadable")}
              </p>
            )}
            <div className="divide-border divide-y">
              {page.chunks.map((chunk, index) => (
                <div key={index} className="py-4 first:pt-0 last:pb-0">
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <MarkdownContent content={chunk} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
