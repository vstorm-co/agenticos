"use client";

import { Download } from "lucide-react";

import { Button, Skeleton } from "@/components/ui";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { useFileDownload, useWorkspaceFileBytes, useWorkspaceFileText } from "@/hooks";
import { isMarkdown, isTextual, type FileSource } from "@/lib/workspace-files";

interface FilePreviewProps {
  source: FileSource;
  path: string;
  /** Markdown only: show the source instead of the rendered document. */
  asSource?: boolean;
}

/**
 * One file, shown as whatever it turned out to be.
 *
 * The suffix decides which *request* to make - text or bytes - and nothing more.
 * Whether what came back can be displayed is the server's answer, read off the
 * response type: it decides what may be served inline (raster images and PDFs, never
 * SVG or HTML), and a second list of suffixes here would be a second answer to the
 * same question that drifts the first time either moves.
 */
export function FilePreview({ source, path, asSource = false }: FilePreviewProps) {
  if (isTextual(path)) return <TextBody source={source} path={path} asSource={asSource} />;
  return <BytesBody source={source} path={path} />;
}

function BytesBody({ source, path }: { source: FileSource; path: string }) {
  const { url, mediaType, isLoading, error } = useWorkspaceFileBytes(source, path);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error !== null) return <Unshowable source={source} path={path} reason={error} />;
  if (url === null) return null;

  if (mediaType?.startsWith("image/") === true)
    // A plain `img` and not `next/image`: the source is a blob URL made in this
    // browser from bytes fetched with the organization header, and the optimizer
    // would need a URL it could fetch server-side - which is exactly the request
    // that would arrive without that header.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt={path} className="max-h-[70vh] w-full object-contain" />;

  if (mediaType === "application/pdf")
    // An iframe rather than an object or an embed: it is the element every browser
    // routes to its own PDF viewer, and that viewer renders the document without
    // handing it this page's DOM. The blob is only ever built from a response the
    // API itself typed `application/pdf` - which is why the branch is on the type
    // and not on the suffix.
    return <iframe src={url} title={path} className="h-[70vh] w-full rounded-md border-0" />;

  // The server did not serve it as something displayable, whatever the suffix
  // suggested. A broken `<img>` with nothing saying why is the worst of the three
  // answers; the download is the one that works.
  return (
    <Unshowable
      source={source}
      path={path}
      reason="This one cannot be shown here — the server serves it as a file."
    />
  );
}

function TextBody({ source, path, asSource }: Required<FilePreviewProps>) {
  const { file, isLoading, error } = useWorkspaceFileText(source, path);

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (error !== null) return <Unshowable source={source} path={path} reason={error} />;
  if (file === null) return null;

  return (
    <div className="space-y-2">
      {isMarkdown(path) && !asSource ? (
        <div className="max-h-[70vh] overflow-auto">
          <MarkdownContent content={file.content} />
        </div>
      ) : (
        <pre className="bg-muted max-h-[70vh] overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
          {file.content}
        </pre>
      )}
      {file.truncated && (
        <p className="text-muted-foreground text-xs">
          Shortened. The agent reads the whole file, and the download holds all of it.
        </p>
      )}
    </div>
  );
}

/** Why this file is not on screen, with the way to read it anyway. */
function Unshowable({
  source,
  path,
  reason,
}: {
  source: FileSource;
  path: string;
  reason: string;
}) {
  const { download, error } = useFileDownload(source);

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-sm">{reason}</p>
      <Button variant="outline" size="sm" onClick={() => download(path)}>
        <Download className="h-3.5 w-3.5" />
        Download it
      </Button>
      {/* A container-backed host refuses a binary either way, so the offer above can
          fail too - and silently, before this. */}
      {error !== null && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
