"use client";

import { useId, useState } from "react";
import { AlertTriangle, SlidersHorizontal } from "lucide-react";

import { Alert, AlertDescription, Button, DialogFooter, Input, Label } from "@/components/ui";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { cn } from "@/lib/utils";
import { FileEditor } from "@/components/files";
import { ResourceActions } from "@/components/sharing/resource-actions";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { ImproveContextButton } from "@/components/authoring/improve-skill-button";
import { displayName } from "@/components/context/file-name";
import type { ContextEdit } from "@/hooks/use-context";
import type { ContextFile } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ContextEditorProps {
  file: ContextFile;
  /** A viewer reads a file; only an editor gets the write controls. */
  canEdit: boolean;
  isSaving: boolean;
  onSave: (edit: ContextEdit) => Promise<void>;
  onCancel: () => void;
  onDelete?: () => void;
}

/**
 * Edit an existing context file.
 *
 * The same shape as a skill: the facts about the file in a strip at the top, the
 * body in the pane every file in this product is read in - rendered by default,
 * source behind a toggle - and one footer at the bottom. It was a flat form with
 * a bare textarea, so Markdown that an agent would receive as Markdown was
 * written and read as raw asterisks, and a context file looked like a different
 * kind of thing from a skill for no reason a reader could name.
 *
 * The name is shown but not editable - it is the handle a person and the `link`
 * tool both use, and the API refuses to change it, so a field that looked
 * editable would be a lie.
 *
 * Seeded once, so mount this keyed by file id: the unsaved diff is what decides
 * whether to warn about the blast radius, and reseeding it mid-edit would
 * discard somebody's typing.
 */
export function ContextEditor({
  file,
  canEdit,
  isSaving,
  onSave,
  onCancel,
  onDelete,
}: ContextEditorProps) {
  const t = useTranslations("context");
  const [description, setDescription] = useState(file.description ?? "");
  const [content, setContent] = useState(file.content);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const metadataId = useId();

  const editedDescription = description.trim() === "" ? null : description.trim();
  const changed = editedDescription !== file.description || content !== file.content;

  const save = async (): Promise<boolean> => {
    try {
      await onSave({ description: editedDescription, content });
      return true;
    } catch {
      // The mutation reports the failure; leaving must keep the unsaved text.
      return false;
    }
  };
  useUnsavedChanges(`context-editor:${file.id}`, {
    dirty: canEdit && changed,
    save,
    discard: () => {
      setDescription(file.description ?? "");
      setContent(file.content);
    },
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Above the pane rather than inside it: these are facts about the file,
          not about the body being read. Every column is label / control / helper
          from the top, so the controls share one line.

          The description is on its own row under them. It is a sentence, and a
          sentence in a 20rem column beside three narrow controls wraps to three
          lines and pushes the pane down - it needs the width, and the controls
          do not. */}
      <div
        id={metadataId}
        className={cn(
          "shrink-0 space-y-4 rounded-md border p-3 max-md:max-h-[30dvh] max-md:overflow-y-auto",
          !metadataOpen && "max-md:hidden",
        )}
      >
        <div className="space-y-1.5">
          <Label htmlFor="context-description">{t("description")}</Label>
          <Input
            id="context-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("whatIsInIt")}
            maxLength={500}
            readOnly={!canEdit}
          />
          <p className="text-muted-foreground text-xs">{t("shownWhenLinked")}</p>
          <p className="text-muted-foreground text-xs">{t("bindingSettingsHint")}</p>
          <p className="text-muted-foreground text-xs">{t("textOnlyBinaryElsewhere")}</p>
        </div>
      </div>

      <FileEditor
        initialMode="source"
        name={displayName(file.name, file.format)}
        content={content}
        canEdit={canEdit}
        onChange={setContent}
        toolbar={
          <Button
            variant={metadataOpen ? "secondary" : "ghost"}
            size="icon"
            className="shrink-0 md:hidden"
            aria-expanded={metadataOpen}
            aria-controls={metadataId}
            onClick={() => setMetadataOpen(!metadataOpen)}
          >
            <SlidersHorizontal aria-hidden className="size-4" />
            <span className="sr-only">{t("description")}</span>
          </Button>
        }
      />

      {changed && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{t("savingReachesEveryAgent")}</AlertDescription>
        </Alert>
      )}

      <DialogFooter className="shrink-0 flex-row items-center max-md:pt-2">
        <div className="mr-auto flex items-center gap-2">
          <ShareResourceButton
            compact
            resourceType="context"
            resourceId={file.id}
            name={file.name}
            canManage={canEdit}
          />
          {canEdit && <ImproveContextButton contextId={file.id} unsaved={changed} />}
          {canEdit && onDelete && (
            <ResourceActions name={file.name} onDelete={onDelete} disabled={isSaving} />
          )}
        </div>
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? t("cancel") : t("close")}
        </Button>
        {canEdit && (
          <Button onClick={() => void save()} loading={isSaving} disabled={!changed}>
            {t("save")}
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
