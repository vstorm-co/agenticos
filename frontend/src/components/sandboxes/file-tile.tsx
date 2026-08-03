"use client";

import {
  FileArchive,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
} from "lucide-react";

/** What kind of file this is, as far as an icon is concerned. */
export type FileKind = "image" | "code" | "sheet" | "doc" | "archive" | "text";

const BY_SUFFIX: Record<string, FileKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  py: "code",
  js: "code",
  ts: "code",
  tsx: "code",
  jsx: "code",
  json: "code",
  yaml: "code",
  yml: "code",
  toml: "code",
  sh: "code",
  sql: "code",
  html: "code",
  css: "code",
  csv: "sheet",
  tsv: "sheet",
  xlsx: "sheet",
  md: "doc",
  markdown: "doc",
  pdf: "doc",
  docx: "doc",
  zip: "archive",
  tar: "archive",
  gz: "archive",
};

const ICONS: Record<FileKind, typeof FileText> = {
  image: FileImage,
  code: FileCode,
  sheet: FileSpreadsheet,
  doc: FileType,
  archive: FileArchive,
  text: FileText,
};

/** The suffix, lowercased, without the dot. Empty for a file that has none. */
export function suffixOf(path: string): string {
  const name = path.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function kindOf(path: string): FileKind {
  return BY_SUFFIX[suffixOf(path)] ?? "text";
}

/**
 * Whether a preview can show this in place.
 *
 * Raster only, and SVG deliberately absent: it carries script, and the API refuses
 * to serve one inline for that reason - so offering a preview would be a promise the
 * server will not keep.
 */
export function isPreviewable(path: string): boolean {
  return ["png", "jpg", "jpeg", "gif", "webp"].includes(suffixOf(path));
}

/** The icon for a path, so a listing is scannable by shape rather than by reading. */
export function FileIcon({ path, className }: { path: string; className?: string }) {
  const Icon = ICONS[kindOf(path)];
  return <Icon className={className} aria-hidden />;
}
