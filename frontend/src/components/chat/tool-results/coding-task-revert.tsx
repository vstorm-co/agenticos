"use client";

import { Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button, ConfirmDialog } from "@/components/ui";
import { useRevertCodingChanges } from "@/hooks/use-coding-changes";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { CodingTaskChanges } from "@/lib/coding-changes-api";

/** The server's current workspace edit decision controls whether undo is offered. */
export function RevertTask({
  changes,
  conversationId,
}: {
  changes: CodingTaskChanges;
  conversationId?: string;
}) {
  const t = useTranslations("chat.tools.codingAgent");
  const errors = useTranslations();
  const [open, setOpen] = useState(false);
  const revert = useRevertCodingChanges();
  if (changes.reverted_at) {
    return <p className="text-muted-foreground text-xs">{t("taskReverted")}</p>;
  }
  // Forked history deliberately drops the source workspace pointer. A copied
  // report must never offer to change the original conversation's files.
  if (!changes.can_revert || conversationId !== changes.conversation_id) return null;
  const conflicts =
    revert.error instanceof ApiError ? revert.error.details?.conflicting_files : null;
  const files = Array.isArray(conflicts)
    ? conflicts.filter((path): path is string => typeof path === "string")
    : [];
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-7 gap-1.5 text-xs"
        data-tour="coding-task-revert"
        onClick={() => {
          revert.reset();
          setOpen(true);
        }}
      >
        <Undo2 className="size-3.5" aria-hidden />
        {t("revertTask")}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t("revertTask")}
        description={t("revertDescription")}
        confirmLabel={t("revertTask")}
        loading={revert.isPending}
        onConfirm={() => revert.mutate(changes.id, { onSuccess: () => setOpen(false) })}
      >
        {revert.error && (
          <div role="alert" className="text-destructive text-sm">
            <p>
              {files.length > 0
                ? t("revertConflict")
                : getErrorMessage(revert.error, errors, t("revertFailed"))}
            </p>
            {files.length > 0 && (
              <ul className="mt-1 list-inside list-disc font-mono text-xs">
                {files.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </ConfirmDialog>
    </>
  );
}
