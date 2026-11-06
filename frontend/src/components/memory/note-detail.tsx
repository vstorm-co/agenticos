"use client";

import { useState } from "react";
import { EyeOff, RotateCcw, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { FileViewer } from "@/components/files";
import { saveBlob, type FileAccess } from "@/lib/file-access";
import { useOrgStore } from "@/stores";
import { Badge, Button, ConfirmDialog } from "@/components/ui";
import type { MemoryNote } from "@/lib/memory-api";

export function NoteDetail({
  note,
  onClose,
  setActive,
  remove,
}: {
  note: MemoryNote;
  onClose: () => void;
  setActive: (id: string, active: boolean) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
}) {
  const t = useTranslations("pages.memory");
  const view = useTranslations("pages.memory.browser");
  const format = useFormatter();
  const org = useOrgStore((state) => state.activeOrgId);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const stamp = note.written_at ?? note.created_at;
  const access: FileAccess = {
    textKey: ["memory", org, "note-text", note.id, note.updated_at, note.written_at],
    bytesKey: ["memory", org, "note-bytes", note.id, note.updated_at, note.written_at],
    readText: async () => ({ content: note.content, truncated: false }),
    readBytes: async () => new Blob([note.content], { type: "text/plain;charset=utf-8" }),
    download: async () =>
      saveBlob(new Blob([note.content], { type: "text/plain;charset=utf-8" }), note.name),
  };
  const details = (
    <div className="space-y-5 py-2">
      <p className="text-muted-foreground text-sm">
        {t("writtenBy", {
          agent: note.agent_name ?? t("anAgent"),
          when: stamp ? format.dateTime(new Date(stamp), { dateStyle: "medium" }) : "",
        })}
      </p>
      {note.description && <p className="text-sm leading-6">{note.description}</p>}
      {note.deactivated_at && <Badge variant="outline">{t("suppressed")}</Badge>}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await setActive(note.id, Boolean(note.deactivated_at));
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
    </div>
  );
  return (
    <>
      <FileViewer
        file={{
          name: note.name,
          modifiedAt: stamp,
          mimeType:
            note.format === "md" || note.format === "markdown" ? "text/markdown" : "text/plain",
        }}
        access={access}
        onClose={onClose}
        extraTabs={[{ value: "memory-details", label: view("noteDetails"), content: details }]}
      />
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
