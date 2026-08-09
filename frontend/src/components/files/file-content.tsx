"use client";

import { useTranslations } from "next-intl";

import { FileBytesView, FileTextView, FileUnavailable } from "./file-render";
import { Skeleton } from "@/components/ui";
import { useFileActions, useFileBytes, useFileText } from "@/hooks";
import type { FileAccess } from "@/lib/file-access";
import { readsAsText, type FileKind } from "@/lib/file-kinds";

interface FileContentProps {
  access: FileAccess;
  kind: FileKind;
  name: string;
  asSource?: boolean;
}

/**
 * One file, fetched and shown.
 *
 * The kind decides which *request* is made and nothing more: characters for a file
 * that is made of them, bytes for everything else. Whether what came back can be
 * displayed is the server's answer, read off the response's type - which is why the
 * two halves are separate components rather than one with a conditional hook.
 */
export function FileContent({ access, kind, name, asSource = false }: FileContentProps) {
  if (readsAsText(kind))
    return <TextBody access={access} kind={kind} name={name} asSource={asSource} />;
  return <BytesBody access={access} name={name} />;
}

function TextBody({ access, kind, name, asSource }: Required<FileContentProps>) {
  const t = useTranslations("files");
  const { file, isLoading, error } = useFileText(access);
  const { download, error: actionError } = useFileActions(access);

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error !== null)
    return <FileUnavailable reason={error} onDownload={download} error={actionError} />;
  return file === null ? null : (
    <div className="space-y-2">
      <FileTextView kind={kind} name={name} text={file.content} asSource={asSource} />
      {file.truncated && <p className="text-muted-foreground text-xs">{t("shortened")}</p>}
    </div>
  );
}

function BytesBody({ access, name }: { access: FileAccess; name: string }) {
  const { url, mediaType, isLoading, error } = useFileBytes(access);
  const { download, error: actionError } = useFileActions(access);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error !== null)
    return <FileUnavailable reason={error} onDownload={download} error={actionError} />;
  return url === null || mediaType === null ? null : (
    <FileBytesView name={name} url={url} mediaType={mediaType} onDownload={download} />
  );
}
