"use client";

import {
  FileArchive,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
} from "lucide-react";

import { suffixOf } from "@/lib/workspace-files";

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

export function kindOf(path: string): FileKind {
  return BY_SUFFIX[suffixOf(path)] ?? "text";
}

/** The icon for a path, so a listing is scannable by shape rather than by reading. */
export function FileIcon({ path, className }: { path: string; className?: string }) {
  const Icon = ICONS[kindOf(path)];
  return <Icon className={className} aria-hidden />;
}
