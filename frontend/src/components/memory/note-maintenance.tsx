"use client";

import { useId, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useNoteMaintenance } from "@/hooks/use-note-maintenance";
import type { MemoryNote } from "@/lib/memory-api";

export function NoteMaintenance({
  note,
  disabled,
  onToggled,
  onRestored,
}: {
  note: MemoryNote;
  disabled: boolean;
  onToggled: (note: MemoryNote) => void;
  onRestored: () => void;
}) {
  const t = useTranslations("pages.memory.browser");
  const common = useTranslations("common");
  const format = useFormatter();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [skip, setSkip] = useState(0);
  const { revisions, toggle, restore } = useNoteMaintenance(note, open, skip);
  const busy = disabled || toggle.isPending || restore.isPending;
  const origin = {
    agent: t("noteRevisionAgent"),
    person: t("noteRevisionPerson"),
    maintenance: t("noteRevisionMaintenance"),
    restore: t("noteRevisionRestore"),
  };
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button
          aria-pressed={Boolean(note.auto_update)}
          variant={note.auto_update ? "secondary" : "outline"}
          disabled={busy || Boolean(note.deactivated_at)}
          onClick={() => toggle.mutate(!note.auto_update, { onSuccess: onToggled })}
        >
          {t("noteAutoUpdate")}
        </Button>
        <Button
          variant="ghost"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
        >
          {t("noteHistory")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("noteAutoUpdateHint")}</p>
      <div id={panelId} hidden={!open} className="space-y-3">
        {revisions.isPending && <p role="status">{common("loading")}</p>}
        {revisions.isError && <p role="alert">{t("noteHistoryError")}</p>}
        {revisions.data?.total === 0 && <p>{t("noteHistoryEmpty")}</p>}
        {revisions.data?.items.map((item) => (
          <details key={item.id} className="space-y-2 rounded-md border p-3">
            <summary className="cursor-pointer text-sm">
              {t("noteRevisionLabel", {
                origin: origin[item.changed_by],
                when: format.dateTime(new Date(item.replaced_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </summary>
            <pre className="max-h-52 overflow-auto text-sm whitespace-pre-wrap">{item.content}</pre>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => restore.mutate(item.id, { onSuccess: onRestored })}
            >
              {t("noteRestoreVersion")}
            </Button>
          </details>
        ))}
        <div className="flex gap-2">
          {skip > 0 && (
            <Button size="sm" variant="ghost" onClick={() => setSkip(Math.max(0, skip - 5))}>
              {t("noteNewerVersions")}
            </Button>
          )}
          {revisions.data && skip + revisions.data.items.length < revisions.data.total && (
            <Button size="sm" variant="ghost" onClick={() => setSkip(skip + 5)}>
              {t("noteOlderVersions")}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
