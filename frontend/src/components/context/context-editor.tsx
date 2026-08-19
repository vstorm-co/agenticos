"use client";

import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Alert,
  AlertDescription,
  Button,
  DialogFooter,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { FileEditor } from "@/components/files";
import { DEFAULT_FORMAT, FORMATS, displayName } from "@/components/context/file-name";
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
  const [mode, setMode] = useState<ContextMode>(file.mode);
  const [format, setFormat] = useState(file.format);
  const [content, setContent] = useState(file.content);
  const [enabled, setEnabled] = useState(file.enabled);

  /**
   * What the format select offers.
   *
   * The catalog, plus whatever this file already holds when that is something
   * else. The column took free text until this became a select, so a file may
   * say `html` or `markdown` - and a `<Select>` whose value matches no option
   * renders empty, which reads as a file with no format at all. Keeping the
   * stored value as an option also keeps opening a file from counting as an
   * edit, which is what deciding it "really means md" would have done.
   */
  const formats = useMemo(() => {
    const stored = file.format.trim();
    return (FORMATS as readonly string[]).includes(stored) ? FORMATS : [...FORMATS, stored];
  }, [file.format]);

  const editedDescription = description.trim() === "" ? null : description.trim();
  const editedFormat = format.trim() || DEFAULT_FORMAT;
  const changed =
    editedDescription !== file.description ||
    content !== file.content ||
    editedFormat !== file.format ||
    mode !== file.mode ||
    enabled !== file.enabled;

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
        <div className="flex flex-wrap items-start gap-4">
          <div className="w-40 shrink-0 space-y-1.5">
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
            <p className="text-muted-foreground text-xs">
              {t(mode === "inject" ? "modeInjectHint" : "modeLinkHint")}
            </p>
          </div>
          <div className="w-32 shrink-0 space-y-1.5">
            <Label htmlFor="context-format">{t("format")}</Label>
            <Select value={format} onValueChange={setFormat} disabled={!canEdit}>
              <SelectTrigger id="context-format" className="font-mono">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {formats.map((option) => (
                  <SelectItem key={option} value={option} className="font-mono">
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("formatHint")}</p>
          </div>
          <div className="shrink-0 space-y-1.5">
            <Label htmlFor="context-enabled">{t("enabled")}</Label>
            {/* Centred on the input row: the switch is shorter than an input, and
                sitting on the row's top edge it reads as misplaced. */}
            <div className="flex h-9 items-center">
              <Switch
                id="context-enabled"
                checked={enabled}
                onCheckedChange={setEnabled}
                disabled={!canEdit}
              />
            </div>
          </div>
        </div>

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

      <FileEditor
        name={displayName(file.name, format)}
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
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? t("cancel") : t("close")}
        </Button>
        {canEdit && (
          <Button
            onClick={() =>
              onSave({
                description: editedDescription,
                content,
                format: editedFormat,
                mode,
                enabled,
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
