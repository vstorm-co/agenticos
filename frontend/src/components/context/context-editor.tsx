"use client";

import { useState } from "react";

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import type { ContextEdit } from "@/hooks/use-context";
import type { ContextFile, ContextMode } from "@/types/providers";
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
 * The name is shown but not editable - it is the handle a person and the `link`
 * tool both use, and the API refuses to change it, so a field that looked
 * editable would be a lie. Everything else is one flat form, since a context
 * file is a single body with no attachments.
 */
export function ContextEditor({ file, canEdit, isSaving, onSave, onCancel }: ContextEditorProps) {
  const t = useTranslations("context");
  const [description, setDescription] = useState(file.description ?? "");
  const [mode, setMode] = useState<ContextMode>(file.mode);
  const [format, setFormat] = useState(file.format);
  const [content, setContent] = useState(file.content);
  const [enabled, setEnabled] = useState(file.enabled);

  function handleSave() {
    onSave({
      description: description.trim() === "" ? null : description.trim(),
      content,
      format: format.trim() || "md",
      mode,
      enabled,
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <span className="font-mono text-sm font-medium">{file.name}</span>
        <div className="w-40 space-y-1.5">
          <Label htmlFor="context-mode">{t("mode")}</Label>
          <Select
            value={mode}
            onValueChange={(value) => setMode(value as ContextMode)}
            disabled={!canEdit}
          >
            <SelectTrigger id="context-mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inject">{t("modeInject")}</SelectItem>
              <SelectItem value="link">{t("modeLink")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-28 space-y-1.5">
          <Label htmlFor="context-format">{t("format")}</Label>
          <Input
            id="context-format"
            value={format}
            onChange={(event) => setFormat(event.target.value)}
            className="font-mono"
            disabled={!canEdit}
            maxLength={16}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={enabled} onCheckedChange={setEnabled} disabled={!canEdit} />
          {t("enabled")}
        </label>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="context-description">{t("description")}</Label>
        <Input
          id="context-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder={t("whatIsInIt")}
          maxLength={500}
          disabled={!canEdit}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col space-y-1.5">
        <Label htmlFor="context-content">{t("content")}</Label>
        <Textarea
          id="context-content"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          className="min-h-72 flex-1 font-mono text-sm"
          disabled={!canEdit}
        />
      </div>

      {canEdit && (
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSave} disabled={isSaving}>
            {t("save")}
          </Button>
        </div>
      )}
    </div>
  );
}
