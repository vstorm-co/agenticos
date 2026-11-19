"use client";

import { useId, useState } from "react";
import { Download, EyeOff, RotateCcw, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { saveBlob } from "@/lib/file-access";
import {
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  MarkdownEditor,
  MarkdownModeToggle,
  type MarkdownMode,
} from "@/components/ui";
import { DIALOG_WIDE, DIALOG_COLUMN, DIALOG_BODY } from "@/lib/dialog-sizes";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import type { MemoryNote } from "@/lib/memory-api";

export function NoteDetail({
  note,
  onClose,
  setActive,
  remove,
  update,
}: {
  note: MemoryNote;
  onClose: () => void;
  setActive: (id: string, active: boolean) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
  update: (note: MemoryNote, content: string) => Promise<boolean>;
}) {
  const t = useTranslations("pages.memory");
  const view = useTranslations("pages.memory.browser");
  const common = useTranslations("common");
  const files = useTranslations("files");
  const format = useFormatter();
  const unsavedId = useId();
  const [original] = useState(note);
  const [mode, setMode] = useState<MarkdownMode>("preview");
  const [content, setContent] = useState(note.content);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = content !== original.content;
  const stamp = note.written_at ?? note.created_at;
  const save = async (): Promise<boolean> => {
    if (busy || !content.trim()) return false;
    setBusy(true);
    try {
      if (!(await update(original, content))) return false;
      onClose();
      return true;
    } finally {
      setBusy(false);
    }
  };
  useUnsavedChanges(unsavedId, { dirty, save, discard: onClose });
  const close = () => {
    if (!busy) useUnsavedChangesStore.getState().leave(onClose, [unsavedId]);
  };
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && close()}>
        <DialogContent dismissible={!busy} className={`${DIALOG_WIDE} ${DIALOG_COLUMN}`}>
          <DialogHeader>
            <DialogTitle>{note.name}</DialogTitle>
            <DialogDescription>{view("editNoteHint")}</DialogDescription>
          </DialogHeader>
          <div className={`${DIALOG_BODY} space-y-4`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-muted-foreground text-xs">
                {t("writtenBy", {
                  agent: note.agent_name ?? t("anAgent"),
                  when: stamp ? format.dateTime(new Date(stamp), { dateStyle: "medium" }) : "",
                })}
              </p>
              {note.deactivated_at && <Badge variant="outline">{t("suppressed")}</Badge>}
            </div>
            {note.description && (
              <p className="text-muted-foreground text-sm">{note.description}</p>
            )}
            <MarkdownEditor
              mode={mode}
              toolbar={<MarkdownModeToggle mode={mode} onChange={setMode} />}
              label={view("noteContent")}
              value={content}
              onChange={setContent}
              rows={18}
              maxLength={100_000}
              disabled={busy}
            />
          </div>
          <DialogFooter className="flex-wrap sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() =>
                  saveBlob(new Blob([content], { type: "text/plain;charset=utf-8" }), note.name)
                }
              >
                <Download className="size-4" aria-hidden />
                {files("download")}
              </Button>
              <Button
                variant="outline"
                disabled={busy || dirty}
                onClick={async () => {
                  setBusy(true);
                  try {
                    if (await setActive(note.id, Boolean(note.deactivated_at))) onClose();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {note.deactivated_at ? (
                  <RotateCcw className="size-4" aria-hidden />
                ) : (
                  <EyeOff className="size-4" aria-hidden />
                )}
                {t(note.deactivated_at ? "restore" : "suppress")}
              </Button>
              <Button variant="ghost" disabled={busy} onClick={() => setConfirming(true)}>
                <Trash2 className="size-4" aria-hidden />
                {t("delete")}
              </Button>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={close} disabled={busy}>
                {common("cancel")}
              </Button>
              <Button
                onClick={() => void save()}
                loading={busy}
                disabled={!dirty || !content.trim() || busy}
              >
                {common("save")}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={view("deleteNote")}
        description={view("deleteNoteHint", { name: note.name })}
        destructive
        confirmLabel={t("delete")}
        loading={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            if (await remove(note.id)) onClose();
          } finally {
            setBusy(false);
          }
        }}
      />
    </>
  );
}
