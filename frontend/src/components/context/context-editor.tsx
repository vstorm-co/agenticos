"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, Button, DialogFooter, Input, Label } from "@/components/ui";
import { FileEditor } from "@/components/files";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { displayName } from "@/components/context/file-name";
import type { ContextEdit } from "@/hooks/use-context";
import type { ContextFile } from "@/types/providers";
import { useTranslations } from "next-intl";

interface ContextEditorProps {
  file: ContextFile;
  /** A viewer reads a file; only an editor gets the write controls. */
  canEdit: boolean;
  isSaving: boolean;
  onSave: (edit: ContextEdit) => void;
  onCancel: () => void;
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
export function ContextEditor({ file, canEdit, isSaving, onSave, onCancel }: ContextEditorProps) {
  const t = useTranslations("context");
  const [description, setDescription] = useState(file.description ?? "");
  const [content, setContent] = useState(file.content);

  const editedDescription = description.trim() === "" ? null : description.trim();
  const changed = editedDescription !== file.description || content !== file.content;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Above the pane rather than inside it: these are facts about the file,
          not about the body being read. Every column is label / control / helper
          from the top, so the controls share one line.

          The description is on its own row under them. It is a sentence, and a
          sentence in a 20rem column beside three narrow controls wraps to three
          lines and pushes the pane down - it needs the width, and the controls
          do not. */}
      <div className="space-y-4 rounded-md border p-3">
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
        </div>
      </div>

      <p className="text-muted-foreground text-xs">{t("bindingSettingsHint")}</p>
      <FileEditor
        initialMode="source"
        name={displayName(file.name, file.format)}
        content={content}
        canEdit={canEdit}
        onChange={setContent}
        footer={<p className="text-muted-foreground text-xs">{t("textOnlyBinaryElsewhere")}</p>}
      />

      {changed && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{t("savingReachesEveryAgent")}</AlertDescription>
        </Alert>
      )}

      <DialogFooter>
        <ShareResourceButton
          resourceType="context"
          resourceId={file.id}
          name={file.name}
          canManage={canEdit}
          className="sm:mr-auto"
        />
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? t("cancel") : t("close")}
        </Button>
        {canEdit && (
          <Button
            onClick={() =>
              onSave({
                description: editedDescription,
                content,
              })
            }
            disabled={!changed || isSaving}
          >
            {t("save")}
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
