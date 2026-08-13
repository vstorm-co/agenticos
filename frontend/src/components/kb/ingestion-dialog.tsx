"use client";

import { useState } from "react";
import { toast } from "sonner";

import { IngestionSettings } from "@/components/kb/ingestion-settings";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { submitFailure } from "@/lib/api-error";
import { INGESTION_FORM_FIELDS, ingestionProblems, sameIngestion } from "@/lib/ingestion-config";
import type { IngestionConfig } from "@/types";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

interface IngestionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The collection's configuration as the server currently holds it. */
  config: IngestionConfig;
  collectionName: string;
  onSave: (config: IngestionConfig) => Promise<unknown>;
}

/**
 * Editing how a collection reads its documents, from now on.
 *
 * "From now on" is the whole reason this is a dialog with its own sentence
 * rather than an inline form: the change takes effect for the next upload and
 * re-parses nothing, so a collection can hold documents read three different
 * ways - which is exactly what the parser column on the document list is for.
 */
export function IngestionDialog({
  open,
  onOpenChange,
  config,
  collectionName,
  onSave,
}: IngestionDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("kb");
  const [draft, setDraft] = useState<IngestionConfig>(config);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  // Reopening shows what the server holds, not what was abandoned last time -
  // and a save elsewhere (or by somebody else) must not leave a stale draft
  // behind to be posted back over it.
  // Both called unconditionally, combined after - `||` would skip the second
  // hook on the render where the first is true.
  const opened = useChanged(open);
  const configMoved = useChanged(config);
  if (opened || configMoved) {
    if (open) {
      setDraft(config);
      setErrors({});
    }
  }

  const problems = ingestionProblems(draft, t);
  const changed = !sameIngestion(draft, config);
  const canSave = changed && Object.keys(problems).length === 0;

  const handleSave = async () => {
    if (!canSave) return;
    setIsSaving(true);
    try {
      await onSave(draft);
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(error, { fields: [...INGESTION_FORM_FIELDS] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Header and footer stay put; only the settings scroll. Save is the way
          out of a long form and must not be the thing that scrolls away. Wide
          because the settings form lays its fields out in columns. */}
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("ingestionSettings")}</DialogTitle>
          <DialogDescription>
            {t.rich("ingestionSettingsDescription", {
              name: collectionName,
              mono: (chunks) => <span className="text-foreground font-mono text-xs">{chunks}</span>,
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
          <IngestionSettings
            idPrefix="kb-ingestion"
            value={draft}
            onChange={setDraft}
            errors={{ ...problems, ...errors }}
            disabled={isSaving}
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button type="button" onClick={handleSave} disabled={!canSave || isSaving}>
            {isSaving ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
