"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import { FileViewer } from "@/components/files";
import { Button } from "@/components/ui";
import {
  isWorkflowMediaScopeCurrent,
  useWorkflowMediaScope,
} from "@/hooks/use-workflow-media-scope";
import { saveBlob, type FileAccess } from "@/lib/file-access";
import { qk } from "@/lib/query-keys";
import { canPreviewWorkflowMedia, readWorkflowMediaPreview } from "@/lib/workflows/media-preview";
import type { WorkflowRunFile } from "@/lib/workflows/types";

/** Account, organization, run and file changes unmount the viewer and its byte URL. */
export function RunFilePreview({ runId, file }: { runId: string; file: WorkflowRunFile }) {
  const scope = useWorkflowMediaScope();
  return (
    <ScopedPreview
      key={JSON.stringify([scope, runId, file.id, file.content_type, file.byte_size])}
      runId={runId}
      file={file}
      scope={scope}
    />
  );
}

function ScopedPreview({
  runId,
  file,
  scope,
}: {
  runId: string;
  file: WorkflowRunFile;
  scope: string;
}) {
  const t = useTranslations("pages.workflows");
  const [open, setOpen] = useState(false);
  const [generation, setGeneration] = useState(0);
  const instance = useId();
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const name = file.filename ?? file.id;
  const access = useMemo<FileAccess>(() => {
    const assertCurrent = () => {
      if (!mounted.current || !isWorkflowMediaScopeCurrent(scope)) throw new Error();
    };
    const read = async (signal?: AbortSignal) => {
      assertCurrent();
      const bytes = await readWorkflowMediaPreview(runId, file, signal);
      assertCurrent();
      return bytes;
    };
    const key = qk.workflows.runFilePreview(
      runId,
      file.id,
      scope,
      file.content_type,
      file.byte_size,
      `${instance}:${generation}`,
    );
    return {
      textKey: [...key, "text"],
      bytesKey: [...key, "bytes"],
      retainBytes: false,
      readText: async () => {
        throw new Error();
      },
      readBytes: read,
      download: async () => {
        const bytes = await read();
        saveBlob(bytes, name);
      },
    };
  }, [runId, file, scope, name, instance, generation]);

  if (!canPreviewWorkflowMedia(file)) return null;
  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("runFilePreview", { name })}
        onClick={() => {
          setGeneration((current) => current + 1);
          setOpen(true);
        }}
      >
        <Eye className="size-4" aria-hidden="true" />
      </Button>
      {open && (
        <FileViewer
          file={{ name, mimeType: file.content_type, size: file.byte_size }}
          access={access}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
