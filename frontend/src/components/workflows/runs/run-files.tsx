"use client";

import { useState } from "react";
import { Download, File } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { formatBytes } from "@/lib/utils";
import { downloadWorkflowRunFile } from "@/lib/workflows/runs-api";
import type { WorkflowRunFile } from "@/lib/workflows/types";

/**
 * The files a run's steps stored - downloads, rendered pages, a script's output -
 * each with a way to save it.
 */
export function RunFiles({ runId, files }: { runId: string; files: WorkflowRunFile[] }) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const [saving, setSaving] = useState<string | null>(null);

  async function save(file: WorkflowRunFile) {
    setSaving(file.id);
    try {
      await downloadWorkflowRunFile(runId, file);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setSaving(null);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t("runFiles")}</CardTitle>
        <CardDescription className="text-xs">{t("runFilesCaption")}</CardDescription>
      </CardHeader>
      <CardContent>
        {files.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("runFilesNone")}</p>
        ) : (
          <ul className="divide-border divide-y">
            {files.map((file) => {
              const name = file.filename ?? file.id;
              return (
                <li key={file.id} className="flex items-center gap-2 py-2">
                  <File aria-hidden="true" className="text-muted-foreground size-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">{name}</p>
                    <p className="text-muted-foreground text-xs">
                      {file.content_type} · {formatBytes(file.byte_size)}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("runFileDownload", { name })}
                    disabled={saving === file.id}
                    onClick={() => void save(file)}
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
