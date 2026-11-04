"use client";

import {
  FileArchive,
  FileAudio,
  FileCode,
  FileCode2,
  FileJson,
  File as PlainFile,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
} from "lucide-react";

import { resolveFileKind, type FileKind } from "@/lib/file-kinds";

/**
 * The mark for a file, as an element.
 *
 * Code, structured data, markup and documents stay distinguishable in every
 * listing. Rendering still follows the shared FileKind contract.
 *
 * A switch returning elements rather than a table of components. Nothing is created
 * per render either way, but a static analyser cannot see that through a lookup, and
 * "component created during render" is a real hazard worth the rule being strict about.
 */
function KindIcon({ kind, className }: { kind: FileKind; className?: string }) {
  switch (kind) {
    case "image":
      return <FileImage className={className} aria-hidden />;
    case "video":
      return <FileVideo className={className} aria-hidden />;
    case "audio":
      return <FileAudio className={className} aria-hidden />;
    case "code":
      return <FileCode className={className} aria-hidden />;
    case "json":
      return <FileJson className={className} aria-hidden />;
    case "html":
      return <FileCode2 className={className} aria-hidden />;
    case "csv":
    case "spreadsheet":
      return <FileSpreadsheet className={className} aria-hidden />;
    case "pdf":
      return <FileType className={className} aria-hidden />;
    case "markdown":
    case "document":
    case "text":
      return <FileText className={className} aria-hidden />;
    case "archive":
      return <FileArchive className={className} aria-hidden />;
    default:
      return <PlainFile className={className} aria-hidden />;
  }
}

/**
 * The icon for a file, so a listing is scannable by shape rather than by reading.
 *
 * Takes the file rather than a kind, because every caller has a name and none of
 * them should have to know that resolving one is a separate step - two icon sets
 * over two kind tables is what this replaced.
 */
export function FileIcon({
  name,
  mimeType,
  className,
}: {
  name: string;
  /** What the origin says it is, where it knows. A name is only a suggestion. */
  mimeType?: string | null;
  className?: string;
}) {
  return <KindIcon kind={resolveFileKind(name, mimeType)} className={className} />;
}
