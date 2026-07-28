"use client";

import { useEffect, useState } from "react";

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
import { ingestionOverride, ingestionProblems, overrideSize } from "@/lib/ingestion-config";
import type { IngestionConfig, IngestionOverride } from "@/types";

interface UploadOverrideDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What the collection does, and therefore what "different" is measured from. */
  config: IngestionConfig;
  /** The departure already in force, so reopening shows it rather than the collection. */
  override: IngestionOverride;
  onApply: (override: IngestionOverride) => void;
}

/**
 * Reading the next files differently, without changing the collection.
 *
 * The form starts from the collection's configuration and only what is moved
 * off it is sent — an override is a set of departures, and a key sent with the
 * collection's own value would be recorded as one, marking a document changed
 * when nothing about it was.
 *
 * It sets a departure rather than performing an upload because the page takes
 * files three ways — the button, the file dialog, a drag onto anywhere — and a
 * form that owned the upload would only cover one of them.
 */
export function UploadOverrideDialog({
  open,
  onOpenChange,
  config,
  override,
  onApply,
}: UploadOverrideDialogProps) {
  const [draft, setDraft] = useState<IngestionConfig>(config);

  useEffect(() => {
    if (open) setDraft(applied(config, override));
  }, [open, config, override]);

  const problems = ingestionProblems(draft);
  const pending = ingestionOverride(config, draft);
  const count = overrideSize(pending);
  const canApply = Object.keys(problems).length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Parse the next upload differently</DialogTitle>
          <DialogDescription>
            This applies to each file you add next and is recorded on it. The collection keeps its
            own settings — every later upload goes back to them.
          </DialogDescription>
        </DialogHeader>

        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
          <IngestionSettings
            idPrefix="kb-upload-override"
            value={draft}
            onChange={setDraft}
            errors={problems}
          />
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onApply({});
              onOpenChange(false);
            }}
          >
            {/* The way back, and the only one: a departure nobody can undo is a
                departure that quietly applies to the next thing dropped here. */}
            Use the collection&apos;s settings
          </Button>
          <Button
            type="button"
            disabled={!canApply}
            onClick={() => {
              onApply(pending);
              onOpenChange(false);
            }}
          >
            {count === 0
              ? "Nothing changed"
              : count === 1
                ? "Apply 1 change"
                : `Apply ${count} changes`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The collection's configuration with the departures already in force put back on. */
function applied(config: IngestionConfig, override: IngestionOverride): IngestionConfig {
  const { image_description: images, ...rest } = override;
  return {
    ...config,
    ...rest,
    image_description: { ...config.image_description, ...images },
  };
}
