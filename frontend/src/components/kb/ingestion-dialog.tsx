"use client";

import { useEffect, useState } from "react";
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
 * ways — which is exactly what the parser column on the document list is for.
 */
export function IngestionDialog({
  open,
  onOpenChange,
  config,
  collectionName,
  onSave,
}: IngestionDialogProps) {
  const [draft, setDraft] = useState<IngestionConfig>(config);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  // Reopening shows what the server holds, not what was abandoned last time —
  // and a save elsewhere (or by somebody else) must not leave a stale draft
  // behind to be posted back over it.
  useEffect(() => {
    if (open) {
      setDraft(config);
      setErrors({});
    }
  }, [open, config]);

  const problems = ingestionProblems(draft);
  const changed = !sameIngestion(draft, config);
  const canSave = changed && Object.keys(problems).length === 0;

  const handleSave = async () => {
    if (!canSave) return;
    setIsSaving(true);
    try {
      await onSave(draft);
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(error, { fields: [...INGESTION_FORM_FIELDS] });
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Header and footer stay put; only the settings scroll. Save is the way
          out of a long form and must not be the thing that scrolls away. */}
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Ingestion settings</DialogTitle>
          <DialogDescription>
            How documents added to{" "}
            <span className="text-foreground font-mono text-xs">{collectionName}</span> are read
            from here on. Nothing already indexed is re-parsed.
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
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} disabled={!canSave || isSaving}>
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
