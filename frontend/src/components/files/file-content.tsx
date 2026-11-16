"use client";

import { useTranslations } from "next-intl";

import { FileBytesView, FileTextView, FileUnavailable } from "./file-render";
import { Skeleton } from "@/components/ui";
import { useFileActions, useFileBytes, useFileText } from "@/hooks";
import type { FileAccess } from "@/lib/file-access";
import { readsAsText, type FileKind } from "@/lib/file-kinds";
import { cn } from "@/lib/utils";

interface FileContentProps {
  access: FileAccess;
  kind: FileKind;
  name: string;
  asSource?: boolean;
  /** Inside a pane that is its own frame: text fills it, with no box of its own. */
  bare?: boolean;
}

/**
 * One file, fetched and shown.
 *
 * The kind decides which *request* is made and nothing more: characters for a file
 * that is made of them, bytes for everything else. Whether what came back can be
 * displayed is the server's answer, read off the response's type - which is why the
 * two halves are separate components rather than one with a conditional hook.
 */
export function FileContent({
  access,
  kind,
  name,
  asSource = false,
  bare = false,
}: FileContentProps) {
  if (readsAsText(kind))
    return <TextBody access={access} kind={kind} name={name} asSource={asSource} bare={bare} />;
  return <BytesBody access={access} name={name} />;
}

function TextBody({ access, kind, name, asSource, bare }: Required<FileContentProps>) {
  const t = useTranslations("files");
  const { file, isLoading, error } = useFileText(access, kind === "html" && !asSource);
  const { download, error: actionError } = useFileActions(access);

  if (isLoading) return <FileContentLoading text />;
  if (error !== null)
    return <FileUnavailable reason={error} onDownload={download} error={actionError} />;
  return file === null ? null : (
    // A column the text fills, so a short file's box is the height of the
    // viewer rather than ending halfway down it.
    <div className={cn("flex h-full flex-col", bare ? "gap-0" : "gap-2")}>
      <div className="min-h-0 flex-1">
        <FileTextView kind={kind} name={name} text={file.content} asSource={asSource} bare={bare} />
      </div>
      {file.truncated && (
        <p className={cn("text-muted-foreground text-xs", bare && "border-t px-3 py-2")}>
          {t("shortened")}
        </p>
      )}
    </div>
  );
}

function BytesBody({ access, name }: { access: FileAccess; name: string }) {
  const { url, mediaType, isLoading, error } = useFileBytes(access);
  const { download, error: actionError } = useFileActions(access);

  if (isLoading) return <FileContentLoading />;
  if (error !== null)
    return <FileUnavailable reason={error} onDownload={download} error={actionError} />;
  return url === null || mediaType === null ? null : (
    <FileBytesView name={name} url={url} mediaType={mediaType} onDownload={download} />
  );
}

/** The reader owns the height, including when the response becomes a download offer. */
function FileContentLoading({ text = false }: { text?: boolean }) {
  const t = useTranslations("states");
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("loading")}
      className="h-full min-h-64 w-full"
    >
      {text ? (
        <div aria-hidden="true" className="h-full min-h-64 space-y-3 p-4">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : (
        <Skeleton aria-hidden="true" className="h-full min-h-64 w-full" />
      )}
    </div>
  );
}
