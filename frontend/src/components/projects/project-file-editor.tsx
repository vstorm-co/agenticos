"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Textarea,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import {
  readEditableProjectFile,
  saveProjectFile,
  type EditableProjectFile,
} from "@/lib/projects-api";
import { qk } from "@/lib/query-keys";

/** A modal editor keeps tree navigation from silently throwing away a draft. */
export function ProjectFileEditor({ projectId, path }: { projectId: string; path: string }) {
  const t = useTranslations("projects.fileManager");
  const tErrors = useTranslations("errors");
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [original, setOriginal] = useState<EditableProjectFile | null>(null);
  const [content, setContent] = useState("");
  const dirty = original !== null && content !== original.content;
  const load = useMutation({
    mutationFn: () => readEditableProjectFile(projectId, path),
    onSuccess: (file) => {
      setOriginal(file);
      setContent(file.content);
    },
  });
  const save = useMutation({
    mutationFn: (file: EditableProjectFile) => saveProjectFile(projectId, path, file),
    onSuccess: async (file) => {
      setOriginal(file);
      setContent(file.content);
      await client.invalidateQueries({ queryKey: qk.projects.detail(projectId) });
    },
  });
  useEffect(() => {
    if (!dirty || !open) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, open]);
  function close() {
    if (save.isPending) return;
    if (dirty) setDiscard(true);
    else setOpen(false);
  }
  const error = load.error ?? save.error;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setOriginal(null);
          setContent("");
          load.reset();
          save.reset();
          setOpen(true);
          load.mutate();
        }}
      >
        <Pencil className="h-3.5 w-3.5" aria-hidden />
        {t("edit")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!value) close();
        }}
      >
        <DialogContent
          className="flex h-[min(85dvh,56rem)] max-w-5xl flex-col gap-4 overflow-hidden"
          onEscapeKeyDown={(event) => {
            event.preventDefault();
            close();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("edit")}</DialogTitle>
            <DialogDescription className="truncate font-mono text-xs" title={path}>
              {path}
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(error, tErrors)}
            </p>
          )}
          {load.isPending ? (
            <p role="status" className="text-muted-foreground text-sm">
              {t("loading")}
            </p>
          ) : (
            original && (
              <Textarea
                aria-label={t("contents")}
                spellCheck={false}
                value={content}
                disabled={save.isPending}
                onChange={(event) => {
                  setContent(event.target.value);
                  save.reset();
                }}
                className="min-h-0 flex-1 resize-none rounded-lg font-mono text-sm leading-relaxed"
              />
            )
          )}
          <DialogFooter className="mt-auto">
            <span className="text-muted-foreground mr-auto self-center text-xs" role="status">
              {dirty ? t("unsaved") : original ? t("saved") : t("textOnly")}
            </span>
            <Button variant="outline" disabled={save.isPending} onClick={close}>
              {t("close")}
            </Button>
            <Button
              disabled={!dirty || save.isPending || !original}
              onClick={() => {
                if (original) save.mutate({ content, revision: original.revision });
              }}
            >
              <Save className="h-4 w-4" aria-hidden />
              {save.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={discard}
        onOpenChange={setDiscard}
        title={t("discardTitle")}
        description={t("discardBody")}
        confirmLabel={t("discard")}
        destructive
        onConfirm={() => {
          setDiscard(false);
          setOpen(false);
        }}
      />
    </>
  );
}
