"use client";

import { Download } from "lucide-react";

import { isPreviewable } from "./file-tile";
import { Button, Skeleton } from "@/components/ui";
import { downloadWorkspaceFile, useWorkspaceBytes, useWorkspaceFile } from "@/hooks";

/**
 * One file, as a picture when it is one and as text when it is not.
 *
 * Shared by the folder browser and the flat "all files" grid, which is the point:
 * opening a file has to mean the same thing in both, and the fallback when a host
 * cannot serve it as text - offer the download - is exactly the branch that would
 * have been forgotten in the second copy.
 */
export function FilePreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  if (isPreviewable(path)) return <ImagePreview workspaceId={workspaceId} path={path} />;
  return <TextPreview workspaceId={workspaceId} path={path} />;
}

function ImagePreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  const { url, isLoading, error } = useWorkspaceBytes(workspaceId, path);

  if (isLoading) return <Skeleton className="m-3 h-32" />;
  if (error !== null) return <p className="text-destructive px-3 pb-3 text-xs">{error}</p>;
  if (url === null) return null;

  return (
    <div className="px-3 pb-3">
      {/* A plain `img` and not `next/image`: the source is a blob URL made in this
          browser from bytes fetched with the organization header, and the optimizer
          would need a URL it could fetch server-side - which is exactly the request
          that would arrive without that header. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={path} className="max-h-64 w-full rounded-md object-contain" />
    </div>
  );
}

function TextPreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  const { file, isLoading, error } = useWorkspaceFile(workspaceId, path);

  if (isLoading) return <Skeleton className="m-3 h-24" />;
  if (error !== null)
    return (
      <div className="px-3 pb-3">
        <p className="text-destructive text-xs">{error}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => void downloadWorkspaceFile(workspaceId, path)}
        >
          <Download className="h-3.5 w-3.5" />
          Download it instead
        </Button>
      </div>
    );
  if (file === null) return null;

  return (
    <pre className="bg-muted mx-3 mb-3 max-h-64 overflow-auto rounded-md p-2 text-[11px] whitespace-pre-wrap">
      {file.content}
    </pre>
  );
}
